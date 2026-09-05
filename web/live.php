<?php
declare(strict_types=1);

/**
 * CRYPTO RADAR - PORTAL BINANCE LIVE (MAINNET, DINHEIRO REAL)
 *
 * FASE 3 do roteiro de dinheiro real: engenharia pronta, mas sem
 * chave real configurada nesta fase (.binance-live.env não existe -
 * ver src/binance_live_executor.py). Enquanto o arquivo não existir,
 * este portal recusa iniciar o loop mesmo que alguém tente.
 *
 * Autocontido de propósito (não faz `require` de testnet.php) - zero
 * risco de tocar o portal testnet já validado.
 */

const BASE_DIR        = __DIR__ . '/..';
const PYTHON_BIN       = BASE_DIR . '/.venv/bin/python3';
const LIVE_ENV_FILE    = BASE_DIR . '/.binance-live.env';
const LOOP_SCRIPT      = BASE_DIR . '/src/binance_live_loop.py';
const RESET_SCRIPT     = BASE_DIR . '/src/binance_live_reset.py';
const CB_CLEAR_SCRIPT  = BASE_DIR . '/src/binance_live_circuit_breaker_clear.py';
const PID_FILE         = BASE_DIR . '/data/binance_live_loop.pid';
const CONFIG_FILE      = BASE_DIR . '/data/binance_live_config.json';
const CB_STATE_FILE    = BASE_DIR . '/data/binance_live_circuit_breaker_state.json';
const OPEN_FILE        = BASE_DIR . '/data/binance_live_open_positions.csv';
const LEDGER_FILE      = BASE_DIR . '/data/binance_live_trades.csv';
const LOG_FILE         = BASE_DIR . '/data/binance_live.log';
const LOOP_LOG         = BASE_DIR . '/data/binance_live_loop_stdout.log';

const DEFAULT_NOTIONAL = 10.0;
const MIN_NOTIONAL     = 5.0;
const MAX_NOTIONAL     = 100.0;

const DEFAULT_BASELINE_CAPITAL = 500.0;
const MIN_BASELINE_CAPITAL     = 10.0;
const MAX_BASELINE_CAPITAL     = 1000000.0;

const DEFAULT_MAX_DRAWDOWN_PCT = 10.0;
const MIN_MAX_DRAWDOWN_PCT     = 2.0;
const MAX_MAX_DRAWDOWN_PCT     = 50.0;

function h(mixed $value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function readCsvRows(string $path): array
{
    if (!file_exists($path)) {
        return [];
    }

    $rows = [];
    $fh = fopen($path, 'r');
    if ($fh === false) {
        return [];
    }

    $header = fgetcsv($fh);
    if ($header === false) {
        fclose($fh);
        return [];
    }

    while (($line = fgetcsv($fh)) !== false) {
        if (count($line) !== count($header)) {
            continue;
        }
        $rows[] = array_combine($header, $line);
    }

    fclose($fh);
    return $rows;
}

function renderEquityCurve(array $cumulativePnls): string
{
    $count = count($cumulativePnls);
    if ($count < 2) {
        return '';
    }

    $width = 860;
    $height = 90;
    $padding = 10;

    $min = min(0.0, min($cumulativePnls));
    $max = max(0.0, max($cumulativePnls));
    $range = $max - $min;
    $isFlat = $range <= 0.0;
    if ($isFlat) {
        $range = 1.0;
    }

    $stepX = ($width - $padding * 2) / ($count - 1);
    $zeroY = $height - $padding - ((0.0 - $min) / $range) * ($height - $padding * 2);

    $points = [];
    foreach ($cumulativePnls as $index => $value) {
        $x = $padding + $index * $stepX;
        $normalized = $isFlat ? 0.5 : ($value - $min) / $range;
        $y = $height - $padding - ($normalized * ($height - $padding * 2));
        $points[] = sprintf('%.2f,%.2f', $x, $y);
    }

    $final = end($cumulativePnls);
    $trendUp = $final >= 0;
    $stroke = $trendUp ? '#65dfa0' : '#ff778b';
    $gradientId = 'equityFill-' . ($trendUp ? 'up' : 'down');
    $glowId = 'equityGlow';
    $lastPoint = explode(',', $points[$count - 1]);

    $areaPoints = $points;
    $areaPoints[] = sprintf('%.2f,%.2f', $padding + ($count - 1) * $stepX, $zeroY);
    array_unshift($areaPoints, sprintf('%.2f,%.2f', $padding, $zeroY));

    $gridLines = '';
    foreach ([0.25, 0.5, 0.75] as $fraction) {
        $y = $padding + $fraction * ($height - $padding * 2);
        $gridLines .= sprintf(
            '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#2a1420" stroke-width="1" />',
            $padding,
            $y,
            $width - $padding,
            $y
        );
    }

    return sprintf(
        '<svg viewBox="0 0 %d %d" width="100%%" height="%d" class="equity-curve" role="img" aria-label="curva de ganho/perda acumulado">'
        . '<defs>'
        . '<linearGradient id="%s" x1="0" y1="0" x2="0" y2="1">'
        . '<stop offset="0%%" stop-color="%s" stop-opacity=".32" />'
        . '<stop offset="100%%" stop-color="%s" stop-opacity="0" />'
        . '</linearGradient>'
        . '<filter id="%s" x="-20%%" y="-20%%" width="140%%" height="140%%">'
        . '<feDropShadow dx="0" dy="0" stdDeviation="3" flood-color="%s" flood-opacity=".55" />'
        . '</filter>'
        . '</defs>'
        . '%s'
        . '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#4a2530" stroke-width="1" stroke-dasharray="4 4" />'
        . '<polygon points="%s" fill="url(#%s)" />'
        . '<polyline points="%s" fill="none" stroke="%s" stroke-width="2.5" stroke-linecap="round" '
        . 'stroke-linejoin="round" filter="url(#%s)" />'
        . '<circle cx="%s" cy="%s" r="4" fill="#170808" stroke="%s" stroke-width="2.5" />'
        . '</svg>',
        $width,
        $height,
        $height,
        $gradientId,
        $stroke,
        $stroke,
        $glowId,
        $stroke,
        $gridLines,
        $padding,
        $zeroY,
        $width - $padding,
        $zeroY,
        h(implode(' ', $areaPoints)),
        $gradientId,
        h(implode(' ', $points)),
        $stroke,
        $glowId,
        h($lastPoint[0]),
        h($lastPoint[1]),
        $stroke
    );
}

function fetchLivePrices(array $symbols): array
{
    if (empty($symbols)) {
        return [];
    }

    // Endpoint público do MAINNET (sem API key) - só pra exibir P&L não
    // realizado no portal, não decide nada sozinho (quem abre/fecha é
    // sempre o Python).
    $codes = array_map(static fn(string $s): string => str_replace('/', '', $s), $symbols);
    $url = 'https://api.binance.com/api/v3/ticker/price?symbols='
        . urlencode(json_encode(array_values(array_unique($codes))));

    $context = stream_context_create(['http' => ['timeout' => 4]]);
    $raw = @file_get_contents($url, false, $context);
    if ($raw === false) {
        return [];
    }

    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) {
        return [];
    }

    $prices = [];
    foreach ($decoded as $entry) {
        if (isset($entry['symbol'], $entry['price'])) {
            $prices[$entry['symbol']] = (float) $entry['price'];
        }
    }
    return $prices;
}

function liveEnvConfigured(): bool
{
    return file_exists(LIVE_ENV_FILE);
}

function loadConfig(): array
{
    $defaults = [
        'notional_usdt' => DEFAULT_NOTIONAL,
        'baseline_capital_usdt' => DEFAULT_BASELINE_CAPITAL,
        'max_drawdown_pct' => DEFAULT_MAX_DRAWDOWN_PCT,
    ];
    if (!file_exists(CONFIG_FILE)) {
        return $defaults;
    }
    $raw = json_decode((string) file_get_contents(CONFIG_FILE), true);
    if (!is_array($raw)) {
        return $defaults;
    }
    foreach ($defaults as $key => $default) {
        if (isset($raw[$key]) && is_numeric($raw[$key])) {
            $defaults[$key] = (float) $raw[$key];
        }
    }
    return $defaults;
}

function saveConfig(array $config): void
{
    file_put_contents(CONFIG_FILE, json_encode($config, JSON_PRETTY_PRINT));
}

function loadCbState(): array
{
    $defaults = [
        'tripped' => false, 'tripped_at' => null, 'drawdown_pct_at_trip' => null,
        'cumulative_pnl_usdt_at_trip' => null, 'baseline_reset_at' => null,
        'cleared_at' => null, 'cleared_by' => null, 'alerted' => false,
    ];
    if (!file_exists(CB_STATE_FILE)) {
        return $defaults;
    }
    $raw = json_decode((string) file_get_contents(CB_STATE_FILE), true);
    return is_array($raw) ? array_merge($defaults, $raw) : $defaults;
}

function loopPid(): ?int
{
    if (!file_exists(PID_FILE)) {
        return null;
    }
    $pid = trim((string) file_get_contents(PID_FILE));
    if ($pid === '' || !ctype_digit($pid)) {
        return null;
    }
    return (int) $pid;
}

function isLoopAlive(int $pid): bool
{
    // Sinal primário: o processo existe (equivalente a kill -0). Ao
    // contrário de checar só /proc/$pid/cmdline (que já causou falso
    // "morto" neste projeto por corrida de leitura - ver memória do
    // projeto), a existência do PID nunca é sujeita a essa corrida.
    exec('kill -0 ' . $pid . ' 2>/dev/null', $unused, $exitCode);
    if ($exitCode !== 0) {
        return false;
    }
    // /proc/cmdline aqui é só uma confirmação EXTRA pra descartar
    // reaproveitamento do PID por outro processo - se não der pra ler
    // (corrida, permissão, kernel sem /proc/pid/cmdline), não trata
    // como morto: a existência do PID já é suficiente.
    $cmdlinePath = "/proc/$pid/cmdline";
    if (!file_exists($cmdlinePath)) {
        return true;
    }
    $cmdline = (string) file_get_contents($cmdlinePath);
    if ($cmdline === '') {
        return true;
    }
    return str_contains($cmdline, 'binance_live_loop.py');
}

function loopStatus(): array
{
    $pid = loopPid();
    if ($pid !== null && isLoopAlive($pid)) {
        return ['running' => true, 'pid' => $pid];
    }
    return ['running' => false, 'pid' => null];
}

function startLoop(): void
{
    $status = loopStatus();
    if ($status['running']) {
        return;
    }
    $cmd = 'nohup ' . escapeshellarg(PYTHON_BIN) . ' ' . escapeshellarg(LOOP_SCRIPT)
        . ' >> ' . escapeshellarg(LOOP_LOG) . ' 2>&1 & echo $!';
    exec($cmd);
    usleep(800000);
}

function stopLoop(): void
{
    $status = loopStatus();
    if (!$status['running']) {
        return;
    }
    $pid = (int) $status['pid'];
    exec('kill -TERM ' . $pid);

    // Espera de verdade o processo sair (até 10s) em vez de confiar
    // num sleep fixo - o loop só checa a flag de parada no topo do
    // laço externo, então pode continuar rodando um ciclo em
    // andamento (com retry de rede) bem além de um sleep curto.
    $deadline = microtime(true) + 10.0;
    while (microtime(true) < $deadline) {
        usleep(300000);
        if (!isLoopAlive($pid)) {
            return;
        }
    }

    // Ainda vivo depois de 10s - força encerramento antes de deixar
    // quem chamou (ex: resetAll) prosseguir com o mesmo CSV/exchange.
    exec('kill -KILL ' . $pid);
    usleep(500000);
}

function resetAll(): array
{
    stopLoop();
    $cmd = escapeshellarg(PYTHON_BIN) . ' ' . escapeshellarg(RESET_SCRIPT) . ' 2>&1';
    exec($cmd, $output, $exitCode);
    return ['ok' => $exitCode === 0, 'output' => implode("\n", $output)];
}

function clearCircuitBreaker(): array
{
    $cmd = escapeshellarg(PYTHON_BIN) . ' ' . escapeshellarg(CB_CLEAR_SCRIPT) . ' portal 2>&1';
    exec($cmd, $output, $exitCode);
    return ['ok' => $exitCode === 0, 'output' => implode("\n", $output)];
}

$message = null;
$envConfigured = liveEnvConfigured();

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = $_POST['action'] ?? '';

    if ($action === 'save_risk_config') {
        $notional = filter_input(INPUT_POST, 'notional_usdt', FILTER_VALIDATE_FLOAT);
        $baseline = filter_input(INPUT_POST, 'baseline_capital_usdt', FILTER_VALIDATE_FLOAT);
        $maxDd = filter_input(INPUT_POST, 'max_drawdown_pct', FILTER_VALIDATE_FLOAT);

        if ($notional === false || $notional < MIN_NOTIONAL || $notional > MAX_NOTIONAL) {
            $message = ['type' => 'error', 'text' => sprintf(
                'Valor por posição inválido. Use entre %s e %s USDT.',
                number_format(MIN_NOTIONAL, 2, ',', '.'), number_format(MAX_NOTIONAL, 2, ',', '.')
            )];
        } elseif ($baseline === false || $baseline < MIN_BASELINE_CAPITAL || $baseline > MAX_BASELINE_CAPITAL) {
            $message = ['type' => 'error', 'text' => sprintf(
                'Capital-base inválido. Use entre %s e %s USDT.',
                number_format(MIN_BASELINE_CAPITAL, 2, ',', '.'), number_format(MAX_BASELINE_CAPITAL, 2, ',', '.')
            )];
        } elseif ($maxDd === false || $maxDd < MIN_MAX_DRAWDOWN_PCT || $maxDd > MAX_MAX_DRAWDOWN_PCT) {
            $message = ['type' => 'error', 'text' => sprintf(
                'Limite de drawdown inválido. Use entre %s%% e %s%%.',
                number_format(MIN_MAX_DRAWDOWN_PCT, 1, ',', '.'), number_format(MAX_MAX_DRAWDOWN_PCT, 1, ',', '.')
            )];
        } else {
            saveConfig([
                'notional_usdt' => $notional,
                'baseline_capital_usdt' => $baseline,
                'max_drawdown_pct' => $maxDd,
            ]);
            $message = ['type' => 'ok', 'text' => 'Configuração de risco atualizada.'];
        }
    } elseif ($action === 'start_loop') {
        if (!$envConfigured) {
            $message = ['type' => 'error', 'text' => 'Chave real não configurada (.binance-live.env não existe) - loop não pode ser iniciado.'];
        } else {
            startLoop();
            header('Location: live.php');
            exit;
        }
    } elseif ($action === 'stop_loop') {
        stopLoop();
        header('Location: live.php');
        exit;
    } elseif ($action === 'reset_all') {
        if (($_POST['confirm'] ?? '') !== 'VENDER') {
            $message = ['type' => 'error', 'text' => 'Confirmação incorreta - digite VENDER pra vender tudo.'];
        } else {
            $result = resetAll();
            $message = $result['ok']
                ? ['type' => 'ok', 'text' => 'Posições vendidas de volta pra USDT e zeradas. Histórico de trades e circuit breaker preservados (não alterados por esta ação). Loop ficou desativado.']
                : ['type' => 'error', 'text' => 'Reset terminou com erro: ' . $result['output']];
        }
    } elseif ($action === 'clear_circuit_breaker') {
        if (($_POST['confirm_cb'] ?? '') !== 'on') {
            $message = ['type' => 'error', 'text' => 'Marque a confirmação pra reativar o circuit breaker.'];
        } else {
            $result = clearCircuitBreaker();
            $message = $result['ok']
                ? ['type' => 'ok', 'text' => 'Circuit breaker reativado - abertura de posição nova liberada a partir de agora.']
                : ['type' => 'error', 'text' => 'Falha ao reativar: ' . $result['output']];
        }
    }
}

$status = loopStatus();
$config = loadConfig();
$cbState = loadCbState();
$openPositions = readCsvRows(OPEN_FILE);

$livePrices = fetchLivePrices(array_column($openPositions, 'symbol'));
foreach ($openPositions as &$pos) {
    $code = str_replace('/', '', $pos['symbol'] ?? '');
    $current = $livePrices[$code] ?? null;
    $entry = (float) ($pos['entry_price'] ?? 0);
    $pos['current_price'] = $current;
    $pos['unrealized_pct'] = ($current !== null && $entry > 0) ? ($current / $entry - 1.0) * 100.0 : null;
    $entryCost = is_numeric($pos['entry_cost_usdt'] ?? '') && $pos['entry_cost_usdt'] !== ''
        ? (float) $pos['entry_cost_usdt']
        : $entry * (float) ($pos['quantity'] ?? 0);
    $pos['unrealized_usdt'] = ($current !== null)
        ? ($current * (float) ($pos['quantity'] ?? 0)) - $entryCost
        : null;
    $openedAt = strtotime((string) ($pos['entry_time'] ?? ''));
    $pos['age_hours'] = $openedAt !== false ? (time() - $openedAt) / 3600.0 : null;
}
unset($pos);

$allTrades = readCsvRows(LEDGER_FILE);
$pnlSeries = array_map(
    static fn(array $t): float => is_numeric($t['pnl_usdt'] ?? '') ? (float) $t['pnl_usdt'] : 0.0,
    $allTrades
);
$totalPnl = array_sum($pnlSeries);
$wins = count(array_filter($pnlSeries, static fn(float $v): bool => $v > 0));
$winRate = count($pnlSeries) > 0 ? ($wins / count($pnlSeries)) * 100.0 : null;

$cumulative = [];
$running = 0.0;
foreach ($pnlSeries as $pnl) {
    $running += $pnl;
    $cumulative[] = $running;
}
$equityCurveSvg = renderEquityCurve($cumulative);
$trades = array_slice(array_reverse($allTrades), 0, 20);

// Drawdown atual (mesma fórmula de src/binance_live_circuit_breaker.py, só pra exibição).
$cbCutoff = $cbState['baseline_reset_at'] ?? null;
$cumulativeSinceBaseline = 0.0;
foreach ($allTrades as $t) {
    if ($cbCutoff !== null) {
        $exitTs = strtotime((string) ($t['exit_time'] ?? ''));
        $cutoffTs = strtotime((string) $cbCutoff);
        if ($exitTs === false || $cutoffTs === false || $exitTs <= $cutoffTs) {
            continue;
        }
    }
    $cumulativeSinceBaseline += is_numeric($t['pnl_usdt'] ?? '') ? (float) $t['pnl_usdt'] : 0.0;
}
$currentDrawdownPct = $config['baseline_capital_usdt'] > 0
    ? max(0.0, -$cumulativeSinceBaseline / $config['baseline_capital_usdt'] * 100.0)
    : 0.0;

$logTail = [];
if (file_exists(LOG_FILE)) {
    $lines = file(LOG_FILE, FILE_IGNORE_NEW_LINES);
    if ($lines !== false) {
        $logTail = array_slice($lines, -15);
    }
}
?>
<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="20">
    <title>Crypto Radar - LIVE (dinheiro real)</title>

    <style>
        * { box-sizing: border-box; }

        body {
            margin: 0;
            font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background:
                radial-gradient(1100px 520px at 12% -10%, rgba(220, 40, 60, .10), transparent 60%),
                radial-gradient(900px 480px at 100% 0%, rgba(160, 30, 40, .08), transparent 55%),
                #0d0707;
            color: #f2e9e9;
        }

        header {
            border-bottom: 2px solid #5c1420;
            background: linear-gradient(180deg, #2a0a0d, #150505);
            padding: 24px 30px;
        }

        .header-inner {
            max-width: 1400px;
            margin: auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
            flex-wrap: wrap;
        }

        .brand h1 {
            margin: 0;
            font-size: 25px;
            font-weight: 800;
            letter-spacing: .2px;
            color: #ffdede;
        }

        .brand p { margin: 7px 0 0; color: #d69a9a; font-size: 13px; }
        .brand a { color: #ff9797; text-decoration: none; }
        .brand a:hover { color: #ffbcbc; text-decoration: underline; }

        .status-pill {
            display: flex;
            align-items: center;
            gap: 9px;
            font-size: 13px;
            font-weight: 700;
            padding: 9px 16px;
            border-radius: 999px;
            border: 1px solid #4a1a20;
            background: #200a0c;
        }

        .status-pill.on { color: #ff8a8a; border-color: #7a1f28; background: rgba(255, 90, 90, .12); }
        .status-pill.off { color: #a08080; }
        .status-pill.halted { color: #ffd27a; border-color: #7a5a1f; background: rgba(255, 190, 90, .12); }

        .dot { width: 9px; height: 9px; border-radius: 50%; background: currentColor; }

        main { max-width: 1400px; margin: 0 auto; padding: 32px 30px 60px; }

        .banner {
            padding: 15px 20px;
            border-radius: 14px;
            margin-bottom: 24px;
            font-size: 13px;
            line-height: 1.6;
        }

        .banner-danger { background: linear-gradient(135deg, #3a0d13, #24080c); border: 2px solid #7a1f28; color: #ffb3b3; }
        .banner-neutral { background: linear-gradient(135deg, #241f1f, #1a1616); border: 1px solid #3d3535; color: #cfc4c4; }
        .banner-halted { background: linear-gradient(135deg, #3a2a0d, #241c08); border: 2px solid #7a5a1f; color: #ffe0a3; }
        .banner-ok { background: linear-gradient(135deg, #12351f, #0f2a19); border: 1px solid #245a35; color: #b8f5d0; }
        .banner-error { background: linear-gradient(135deg, #3a0d13, #24080c); border: 1px solid #7a1f28; color: #ffb3b3; }

        .top-row { display: flex; align-items: stretch; gap: 20px; margin-bottom: 28px; flex-wrap: wrap; }
        .top-row > .card { display: flex; flex-direction: column; flex: 1 1 300px; min-width: 0; }
        .top-row > .highlight-card { flex: 1.7 1 460px; }

        .card {
            background: linear-gradient(165deg, #201212, #170d0d);
            border: 1px solid #3d2525;
            border-radius: 16px;
            padding: 24px;
        }

        .card h2 {
            margin: 0 0 16px;
            font-size: 14px;
            font-weight: 700;
            color: #dcb8b8;
            text-transform: uppercase;
            letter-spacing: .6px;
        }

        .highlight-card { padding: 20px 24px 18px; position: relative; overflow: hidden; justify-content: space-between; }
        .highlight-top { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 20px; margin-bottom: 12px; }
        .highlight-label { color: #b08a8a; font-size: 12px; text-transform: uppercase; letter-spacing: .8px; margin-bottom: 10px; }
        .highlight-value { font-size: 32px; font-weight: 800; line-height: 1; letter-spacing: -.3px; }
        .highlight-stats { display: flex; gap: 30px; }
        .highlight-stats > div { display: flex; flex-direction: column; gap: 5px; text-align: right; padding: 4px 0; }
        .highlight-stat-label { color: #b08a8a; font-size: 11px; text-transform: uppercase; letter-spacing: .6px; }
        .highlight-stat-value { font-size: 17px; font-weight: 700; color: #f2e9e9; }

        .equity-wrapper { width: 100%; position: relative; border-top: 1px solid #3d2525; padding-top: 10px; }
        .equity-curve { display: block; width: 100%; height: auto; }

        .field-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
        .field-label { font-size: 12px; color: #b08a8a; min-width: 150px; }

        input[type="number"], input[type="text"] {
            background: #150a0a;
            border: 1px solid #4a2525;
            color: #f2e9e9;
            padding: 11px 13px;
            border-radius: 9px;
            font-size: 14px;
            width: 160px;
        }

        input:focus { outline: none; border-color: #c94a4a; box-shadow: 0 0 0 3px rgba(201, 74, 74, .18); }

        button {
            font-family: inherit;
            font-size: 14px;
            font-weight: 700;
            padding: 11px 20px;
            border-radius: 9px;
            border: none;
            cursor: pointer;
        }

        button:hover { filter: brightness(1.1); }

        .btn-save { background: linear-gradient(135deg, #c94a4a, #8f1f1f); color: #fff; }
        .btn-activate { background: linear-gradient(135deg, #29c073, #1a8f52); color: #fff; }
        .btn-deactivate { background: linear-gradient(135deg, #6a4a4a, #453030); color: #fff; }
        .btn-danger { background: linear-gradient(135deg, #e0495f, #a5293a); color: #fff; }
        .btn-reactivate { background: linear-gradient(135deg, #d99a3a, #a56a1a); color: #fff; }
        button:disabled { background: #2a1c1c; color: #6a5555; cursor: not-allowed; }

        .hint { color: #b08a8a; font-size: 12px; margin-top: 8px; line-height: 1.6; }
        .placeholder-warning { color: #ffd27a; font-weight: 600; }

        .table-wrapper { overflow-x: auto; border-radius: 12px; }
        table { width: 100%; border-collapse: collapse; min-width: 640px; }
        th { background: #150a0a; color: #b08a8a; font-size: 11px; text-transform: uppercase; letter-spacing: .7px; text-align: left; padding: 13px 15px; }
        td { border-top: 1px solid #3d2525; padding: 13px 15px; font-size: 13px; }
        tr:hover td { background: #241414; }

        .symbol { font-weight: 700; color: #fff; }
        .positive { color: #65dfa0; }
        .negative { color: #ff778b; }

        .badge { display: inline-block; padding: 4px 11px; border-radius: 999px; font-size: 11px; font-weight: 700; border: 1px solid transparent; }
        .badge.stop { background: rgba(255, 119, 139, .12); color: #ff778b; border-color: rgba(255, 119, 139, .25); }
        .badge.target { background: rgba(105, 226, 155, .12); color: #69e29b; border-color: rgba(105, 226, 155, .25); }
        .badge.time { background: rgba(176, 138, 138, .12); color: #b08a8a; border-color: rgba(176, 138, 138, .25); }

        pre.log { background: #0d0707; border: 1px solid #3d2525; border-radius: 12px; padding: 16px; font-size: 12px; line-height: 1.7; color: #cfa8a8; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }

        .empty { color: #b08a8a; font-size: 13px; padding: 12px 0; }
        .checkbox-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 13px; }
    </style>
</head>
<body>

<header>
    <div class="header-inner">
        <div class="brand">
            <h1>&#9888; BINANCE MAINNET - PORTAL DE DINHEIRO REAL</h1>
            <p>Ordens reais, saldo real &middot; <a href="index.php">&larr; dashboard</a> &middot; <a href="testnet.php">testnet (fictício) &rarr;</a></p>
        </div>
        <div class="status-pill <?= $cbState['tripped'] ? 'halted' : ($status['running'] ? 'on' : 'off') ?>">
            <span class="dot"></span>
            <?php if ($cbState['tripped']): ?>
                Circuit breaker ATIVO
            <?php elseif ($status['running']): ?>
                Ativo (pid <?= h((string) $status['pid']) ?>)
            <?php else: ?>
                Desativado
            <?php endif; ?>
        </div>
    </div>
</header>

<main>
    <?php if (!$envConfigured): ?>
        <div class="banner banner-neutral">
            <strong>Chave não configurada.</strong> Engenharia pronta (Fase 3 do roteiro), trading real
            desabilitado até <code>.binance-live.env</code> existir - isso só é criado manualmente, com o
            usuário presente (Fase 2 do roteiro). Nenhuma ordem real pode ser enviada neste estado.
        </div>
    <?php elseif ($cbState['tripped']): ?>
        <div class="banner banner-halted">
            <strong>Circuit breaker acionado</strong> em <?= h($cbState['tripped_at'] ?? '-') ?>:
            drawdown de <?= h(number_format((float) ($cbState['drawdown_pct_at_trip'] ?? 0), 1, ',', '.')) ?>%
            (limite configurado: <?= h(number_format($config['max_drawdown_pct'], 1, ',', '.')) ?>%).
            Abertura de posição nova está PAUSADA - posições já abertas continuam sendo monitoradas
            e saem normalmente por STOP/TARGET/TIME. Reative manualmente abaixo quando decidir.
        </div>
    <?php else: ?>
        <div class="banner banner-danger">
            AMBIENTE: BINANCE SPOT MAINNET - DINHEIRO REAL. O loop, quando ativo, roda um ciclo a cada 5
            minutos sozinho (compra/vende de verdade). Drawdown atual desde a última reativação:
            <?= h(number_format($currentDrawdownPct, 1, ',', '.')) ?>% de
            <?= h(number_format($config['max_drawdown_pct'], 1, ',', '.')) ?>% permitido.
        </div>
    <?php endif; ?>

    <?php if ($message !== null): ?>
        <div class="banner <?= $message['type'] === 'ok' ? 'banner-ok' : 'banner-error' ?>">
            <?= h($message['text']) ?>
        </div>
    <?php endif; ?>

    <div class="top-row">
        <div class="card highlight-card">
            <div class="highlight-top">
                <div>
                    <div class="highlight-label">Resultado acumulado (USDT real)</div>
                    <div class="highlight-value <?= $totalPnl >= 0 ? 'positive' : 'negative' ?>">
                        <?= ($totalPnl >= 0 ? '+' : '') . '$' . number_format($totalPnl, 2, ',', '.') ?>
                    </div>
                </div>
                <div class="highlight-stats">
                    <div>
                        <span class="highlight-stat-label">Trades</span>
                        <span class="highlight-stat-value"><?= count($allTrades) ?></span>
                    </div>
                    <div>
                        <span class="highlight-stat-label">Acerto</span>
                        <span class="highlight-stat-value"><?= $winRate === null ? '-' : number_format($winRate, 0) . '%' ?></span>
                    </div>
                </div>
            </div>
            <?php if ($equityCurveSvg !== ''): ?>
                <div class="equity-wrapper"><?= $equityCurveSvg ?></div>
            <?php else: ?>
                <p class="empty">Gráfico aparece a partir do 2º trade fechado.</p>
            <?php endif; ?>
        </div>

        <div class="card">
            <h2>Loop automático</h2>
            <form method="post" class="field-row">
                <?php if ($status['running']): ?>
                    <input type="hidden" name="action" value="stop_loop">
                    <button type="submit" class="btn-deactivate">Desativar</button>
                <?php else: ?>
                    <input type="hidden" name="action" value="start_loop">
                    <button type="submit" class="btn-activate" <?= $envConfigured ? '' : 'disabled' ?>>Ativar</button>
                <?php endif; ?>
            </form>
            <p class="hint">
                <?= $envConfigured
                    ? 'Ciclo a cada 5 minutos até você desativar. DINHEIRO REAL.'
                    : 'Desabilitado - chave real não configurada.' ?>
            </p>
        </div>

        <div class="card">
            <h2>Vender tudo (emergência)</h2>
            <form
                method="post"
                onsubmit="return document.getElementById('confirm_venda').value === 'VENDER';"
            >
                <input type="hidden" name="action" value="reset_all">
                <div class="field-row">
                    <input type="text" id="confirm_venda" name="confirm" placeholder="Digite VENDER" autocomplete="off">
                    <button type="submit" class="btn-danger">Vender tudo agora</button>
                </div>
            </form>
            <p class="hint">Vende posições abertas de volta pra USDT. Histórico de trades e circuit breaker são preservados - NÃO reativa o breaker.</p>
        </div>
    </div>

    <div class="top-row">
        <div class="card">
            <h2>Configuração de risco</h2>
            <form method="post">
                <input type="hidden" name="action" value="save_risk_config">
                <div class="field-row">
                    <span class="field-label">Valor por posição (USDT)</span>
                    <input type="number" name="notional_usdt" step="0.01" min="<?= MIN_NOTIONAL ?>" max="<?= MAX_NOTIONAL ?>"
                        value="<?= h(number_format($config['notional_usdt'], 2, '.', '')) ?>">
                </div>
                <div class="field-row">
                    <span class="field-label">Capital-base (USDT)</span>
                    <input type="number" name="baseline_capital_usdt" step="0.01" min="<?= MIN_BASELINE_CAPITAL ?>" max="<?= MAX_BASELINE_CAPITAL ?>"
                        value="<?= h(number_format($config['baseline_capital_usdt'], 2, '.', '')) ?>">
                </div>
                <div class="field-row">
                    <span class="field-label">Limite de drawdown (%)</span>
                    <input type="number" name="max_drawdown_pct" step="0.1" min="<?= MIN_MAX_DRAWDOWN_PCT ?>" max="<?= MAX_MAX_DRAWDOWN_PCT ?>"
                        value="<?= h(number_format($config['max_drawdown_pct'], 1, '.', '')) ?>">
                </div>
                <button type="submit" class="btn-save">Salvar</button>
            </form>
            <p class="hint placeholder-warning">
                Capital-base e limite de drawdown são placeholders (Fase 3) - ajuste conscientemente
                antes de considerar qualquer chave real (Fase 4).
            </p>
        </div>

        <div class="card">
            <h2>Circuit breaker</h2>
            <p class="hint">
                Estado: <strong><?= $cbState['tripped'] ? 'ACIONADO' : 'normal' ?></strong><br>
                <?php if ($cbState['tripped']): ?>
                    Acionado em <?= h($cbState['tripped_at'] ?? '-') ?>,
                    drawdown <?= h(number_format((float) ($cbState['drawdown_pct_at_trip'] ?? 0), 1, ',', '.')) ?>%.
                <?php else: ?>
                    Drawdown atual: <?= h(number_format($currentDrawdownPct, 1, ',', '.')) ?>%
                    de <?= h(number_format($config['max_drawdown_pct'], 1, ',', '.')) ?>% permitido.
                <?php endif; ?>
            </p>
            <?php if ($cbState['tripped']): ?>
                <form method="post">
                    <input type="hidden" name="action" value="clear_circuit_breaker">
                    <div class="checkbox-row">
                        <input type="checkbox" id="confirm_cb" name="confirm_cb">
                        <label for="confirm_cb">Entendo que isso reativa abertura de novas posições reais.</label>
                    </div>
                    <button type="submit" class="btn-reactivate">Reativar circuit breaker</button>
                </form>
            <?php endif; ?>
        </div>
    </div>

    <div class="card" style="margin-bottom: 28px;">
        <h2>Posições abertas (<?= count($openPositions) ?>)</h2>
        <?php if (empty($openPositions)): ?>
            <p class="empty">Nenhuma posição aberta no momento.</p>
        <?php else: ?>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr><th>Símbolo</th><th>Entrada</th><th>Atual</th><th>Tempo aberto</th><th>P&amp;L não realizado</th><th>Score</th></tr>
                    </thead>
                    <tbody>
                        <?php foreach ($openPositions as $pos):
                            $pct = $pos['unrealized_pct'];
                            $usdt = $pos['unrealized_usdt'];
                            $ageHours = $pos['age_hours'];
                        ?>
                            <tr>
                                <td class="symbol"><?= h($pos['symbol'] ?? '') ?></td>
                                <td><?= h($pos['entry_price'] ?? '') ?></td>
                                <td><?= $pos['current_price'] !== null ? h($pos['current_price']) : '-' ?></td>
                                <td><?= $ageHours !== null ? h(sprintf('%dh%02dm', (int) $ageHours, (int) round(($ageHours - (int) $ageHours) * 60))) : '-' ?></td>
                                <td class="<?= $pct === null ? '' : ($pct >= 0 ? 'positive' : 'negative') ?>">
                                    <?php if ($pct === null || $usdt === null): ?>-<?php else: ?>
                                        <?= ($pct >= 0 ? '+' : '') . number_format($pct, 2, ',', '.') ?>%
                                        (<?= ($usdt >= 0 ? '+' : '') . '$' . number_format($usdt, 2, ',', '.') ?>)
                                    <?php endif; ?>
                                </td>
                                <td><?= h($pos['score'] ?? '') ?></td>
                            </tr>
                        <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
        <?php endif; ?>
    </div>

    <div class="card" style="margin-bottom: 28px;">
        <h2>Últimos trades fechados</h2>
        <?php if (empty($trades)): ?>
            <p class="empty">Nenhum trade fechado ainda.</p>
        <?php else: ?>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr><th>Símbolo</th><th>Saída</th><th>Duração</th><th>Motivo</th><th>Retorno bruto</th><th>Ganho/perda (USDT real)</th></tr>
                    </thead>
                    <tbody>
                        <?php foreach ($trades as $trade):
                            $reason = strtolower((string) ($trade['exit_reason'] ?? ''));
                            $ret = (float) ($trade['gross_return_pct'] ?? 0);
                            $pnlRaw = $trade['pnl_usdt'] ?? '';
                            $pnl = $pnlRaw !== '' ? (float) $pnlRaw : null;
                            $enter = strtotime((string) ($trade['entry_time'] ?? ''));
                            $exit = strtotime((string) ($trade['exit_time'] ?? ''));
                            $durationHours = ($enter !== false && $exit !== false) ? ($exit - $enter) / 3600.0 : null;
                            $exitLabel = $exit !== false ? date('d/m H:i', $exit) : ($trade['exit_time'] ?? '');
                        ?>
                            <tr>
                                <td class="symbol"><?= h($trade['symbol'] ?? '') ?></td>
                                <td><?= h($exitLabel) ?></td>
                                <td><?= $durationHours !== null ? h(sprintf('%dh%02dm', (int) $durationHours, (int) round(($durationHours - (int) $durationHours) * 60))) : '-' ?></td>
                                <td><span class="badge <?= h($reason) ?>"><?= h($trade['exit_reason'] ?? '') ?></span></td>
                                <td class="<?= $ret >= 0 ? 'positive' : 'negative' ?>"><?= ($ret >= 0 ? '+' : '') . number_format($ret, 2, ',', '.') ?>%</td>
                                <td class="<?= $pnl === null ? '' : ($pnl >= 0 ? 'positive' : 'negative') ?>">
                                    <?= $pnl === null ? '-' : ($pnl >= 0 ? '+' : '') . '$' . number_format($pnl, 2, ',', '.') ?>
                                </td>
                            </tr>
                        <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
        <?php endif; ?>
    </div>

    <div class="card">
        <h2>Log recente</h2>
        <?php if (empty($logTail)): ?>
            <p class="empty">Sem log ainda.</p>
        <?php else: ?>
            <pre class="log"><?= h(implode("\n", $logTail)) ?></pre>
        <?php endif; ?>
    </div>
</main>

</body>
</html>
