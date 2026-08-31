<?php
declare(strict_types=1);

/**
 * CRYPTO RADAR - PORTAL BINANCE TESTNET
 *
 * Ativa/desativa o loop contínuo (src/binance_testnet_loop.py),
 * define o valor por posição e acompanha compra/venda no Testnet.
 * Dinheiro fictício - nunca envia ordem real (mainnet).
 */

const BASE_DIR    = __DIR__ . '/..';
const PYTHON_BIN  = BASE_DIR . '/.venv/bin/python3';
const LOOP_SCRIPT = BASE_DIR . '/src/binance_testnet_loop.py';
const PID_FILE    = BASE_DIR . '/data/binance_testnet_loop.pid';
const CONFIG_FILE = BASE_DIR . '/data/binance_testnet_config.json';
const OPEN_FILE   = BASE_DIR . '/data/binance_testnet_open_positions.csv';
const LEDGER_FILE = BASE_DIR . '/data/binance_testnet_trades.csv';
const LOG_FILE    = BASE_DIR . '/data/binance_testnet.log';
const LOOP_LOG    = BASE_DIR . '/data/binance_testnet_loop_stdout.log';

const DEFAULT_NOTIONAL = 15.0;
const MIN_NOTIONAL     = 5.0;
const MAX_NOTIONAL     = 500.0;

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

    // Linhas guia leves em 25/50/75% da altura - só orientação visual,
    // sem valor/label (o card ao lado já mostra os números).
    $gridLines = '';
    foreach ([0.25, 0.5, 0.75] as $fraction) {
        $y = $padding + $fraction * ($height - $padding * 2);
        $gridLines .= sprintf(
            '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#1c2841" stroke-width="1" />',
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
        . '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#324370" stroke-width="1" stroke-dasharray="4 4" />'
        . '<polygon points="%s" fill="url(#%s)" />'
        . '<polyline points="%s" fill="none" stroke="%s" stroke-width="2.5" stroke-linecap="round" '
        . 'stroke-linejoin="round" filter="url(#%s)" />'
        . '<circle cx="%s" cy="%s" r="4" fill="#0b1020" stroke="%s" stroke-width="2.5" />'
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

function loadNotional(): float
{
    if (!file_exists(CONFIG_FILE)) {
        return DEFAULT_NOTIONAL;
    }
    $raw = json_decode((string) file_get_contents(CONFIG_FILE), true);
    if (!is_array($raw) || !isset($raw['notional_usdt']) || !is_numeric($raw['notional_usdt'])) {
        return DEFAULT_NOTIONAL;
    }
    $value = (float) $raw['notional_usdt'];
    return $value > 0 ? $value : DEFAULT_NOTIONAL;
}

function saveNotional(float $value): void
{
    file_put_contents(CONFIG_FILE, json_encode(['notional_usdt' => $value], JSON_PRETTY_PRINT));
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
    $cmdlinePath = "/proc/$pid/cmdline";
    if (!file_exists($cmdlinePath)) {
        return false;
    }
    $cmdline = (string) file_get_contents($cmdlinePath);
    return str_contains($cmdline, 'binance_testnet_loop.py');
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
    exec('kill -TERM ' . (int) $status['pid']);
    usleep(800000);
}

$message = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = $_POST['action'] ?? '';

    if ($action === 'save_notional') {
        $value = filter_input(INPUT_POST, 'notional_usdt', FILTER_VALIDATE_FLOAT);
        if ($value === false || $value < MIN_NOTIONAL || $value > MAX_NOTIONAL) {
            $message = [
                'type' => 'error',
                'text' => sprintf(
                    'Valor inválido. Use um número entre %s e %s USDT.',
                    number_format(MIN_NOTIONAL, 2, ',', '.'),
                    number_format(MAX_NOTIONAL, 2, ',', '.')
                ),
            ];
        } else {
            saveNotional($value);
            $message = ['type' => 'ok', 'text' => 'Valor por posição atualizado.'];
        }
    } elseif ($action === 'start_loop') {
        startLoop();
        header('Location: testnet.php');
        exit;
    } elseif ($action === 'stop_loop') {
        stopLoop();
        header('Location: testnet.php');
        exit;
    }
}

$status = loopStatus();
$notional = loadNotional();
$openPositions = readCsvRows(OPEN_FILE);
$allTrades = readCsvRows(LEDGER_FILE); // ordem cronológica (mais antigo primeiro), do jeito que foi anexado
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
    <title>Crypto Radar - Testnet</title>

    <style>
        * { box-sizing: border-box; }

        body {
            margin: 0;
            font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background:
                radial-gradient(1100px 520px at 12% -10%, rgba(43, 110, 242, .10), transparent 60%),
                radial-gradient(900px 480px at 100% 0%, rgba(105, 226, 155, .06), transparent 55%),
                #0b0f1d;
            color: #e8edf7;
        }

        header {
            border-bottom: 1px solid #1c2540;
            background: linear-gradient(180deg, #101a30, #0d1526);
            padding: 24px 30px;
            box-shadow: 0 1px 0 rgba(255, 255, 255, .03) inset;
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
            background: linear-gradient(135deg, #ffffff, #aab8e0);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }

        .brand p { margin: 7px 0 0; color: #8995ad; font-size: 13px; }
        .brand a { color: #7ea2ff; text-decoration: none; transition: color .15s ease; }
        .brand a:hover { color: #a9c1ff; text-decoration: underline; }

        .status-pill {
            display: flex;
            align-items: center;
            gap: 9px;
            font-size: 13px;
            font-weight: 600;
            padding: 9px 16px;
            border-radius: 999px;
            border: 1px solid #202b45;
            background: #0f1830;
            transition: box-shadow .2s ease;
        }

        .status-pill.on {
            color: #69e29b;
            border-color: #245a3d;
            background: rgba(105, 226, 155, .08);
            box-shadow: 0 0 0 1px rgba(105, 226, 155, .12), 0 0 18px rgba(105, 226, 155, .18);
        }

        .status-pill.off { color: #8995ad; }

        .dot { width: 9px; height: 9px; border-radius: 50%; background: currentColor; }

        .status-pill.on .dot {
            box-shadow: 0 0 0 3px rgba(105, 226, 155, .18);
            animation: pulse 1.8s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: .45; }
        }

        main { max-width: 1400px; margin: 0 auto; padding: 32px 30px 60px; }

        .warning {
            background: linear-gradient(135deg, #34161f, #2a1420);
            border: 1px solid #6c2d40;
            color: #ffc4d0;
            padding: 15px 20px;
            border-radius: 14px;
            margin-bottom: 24px;
            font-size: 13px;
            line-height: 1.6;
            box-shadow: 0 10px 30px -18px rgba(180, 40, 70, .5);
        }

        .banner-ok {
            background: linear-gradient(135deg, #123524, #0f2a1e);
            border-color: #245a3d;
            color: #b8f5d2;
            box-shadow: 0 10px 30px -18px rgba(40, 180, 100, .45);
        }

        .top-row {
            display: flex;
            align-items: stretch;
            gap: 20px;
            margin-bottom: 28px;
        }

        .top-row > .card { display: flex; flex-direction: column; flex: 1 1 0; min-width: 0; }
        .top-row > .highlight-card { flex: 1.7 1 0; }

        @media (max-width: 980px) {
            .top-row { flex-wrap: wrap; }
            .top-row > .card { flex: 1 1 45%; }
        }

        @media (max-width: 620px) {
            .top-row { flex-direction: column; }
            .top-row > .card { flex: 1 1 auto; }
        }

        .card {
            background: linear-gradient(165deg, #131d34, #0f1729);
            border: 1px solid #202b45;
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 20px 40px -28px rgba(0, 0, 0, .7), 0 1px 0 rgba(255, 255, 255, .03) inset;
            transition: border-color .2s ease, transform .2s ease;
        }

        .card:hover { border-color: #2c3a5c; }

        .card h2 {
            margin: 0 0 16px;
            font-size: 14px;
            font-weight: 700;
            color: #c7cfe2;
            text-transform: uppercase;
            letter-spacing: .6px;
        }

        .highlight-card {
            padding: 20px 24px 18px;
            position: relative;
            overflow: hidden;
            justify-content: space-between;
        }

        .highlight-card::before {
            content: "";
            position: absolute;
            inset: 0;
            background: radial-gradient(420px 180px at 0% 0%, rgba(105, 226, 155, .10), transparent 70%);
            pointer-events: none;
        }

        .highlight-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 20px;
            margin-bottom: 12px;
            position: relative;
        }

        .highlight-label {
            color: #8995ad;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: .8px;
            margin-bottom: 10px;
        }

        .highlight-value {
            font-size: 32px;
            font-weight: 800;
            line-height: 1;
            letter-spacing: -.3px;
            text-shadow: 0 0 24px currentColor;
            filter: saturate(1.15);
        }

        .highlight-stats { display: flex; gap: 30px; }

        .highlight-stats > div {
            display: flex;
            flex-direction: column;
            gap: 5px;
            text-align: right;
            padding: 4px 0;
        }

        .highlight-stat-label { color: #8995ad; font-size: 11px; text-transform: uppercase; letter-spacing: .6px; }

        .highlight-stat-value { font-size: 17px; font-weight: 700; color: #eef1fb; }

        .equity-wrapper {
            width: 100%;
            position: relative;
            border-top: 1px solid #1c2841;
            padding-top: 10px;
        }

        .equity-curve { display: block; width: 100%; height: auto; }

        .field-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }

        input[type="number"] {
            background: #0a0f1e;
            border: 1px solid #26324f;
            color: #e8edf7;
            padding: 11px 13px;
            border-radius: 9px;
            font-size: 14px;
            width: 160px;
            transition: border-color .15s ease, box-shadow .15s ease;
        }

        input[type="number"]:focus {
            outline: none;
            border-color: #4d7ef2;
            box-shadow: 0 0 0 3px rgba(77, 126, 242, .18);
        }

        button {
            font-family: inherit;
            font-size: 14px;
            font-weight: 700;
            padding: 11px 20px;
            border-radius: 9px;
            border: none;
            cursor: pointer;
            transition: transform .12s ease, box-shadow .12s ease, filter .12s ease;
        }

        button:hover { transform: translateY(-1px); filter: brightness(1.08); }
        button:active { transform: translateY(0); filter: brightness(.96); }

        .btn-save {
            background: linear-gradient(135deg, #3f7cff, #2b5fe0);
            color: #fff;
            box-shadow: 0 10px 24px -12px rgba(59, 110, 240, .7);
        }

        .btn-activate {
            background: linear-gradient(135deg, #29c073, #1a8f52);
            color: #fff;
            box-shadow: 0 10px 24px -12px rgba(30, 158, 90, .7);
        }

        .btn-deactivate {
            background: linear-gradient(135deg, #e0495f, #a5293a);
            color: #fff;
            box-shadow: 0 10px 24px -12px rgba(177, 58, 75, .7);
        }

        .hint { color: #8995ad; font-size: 12px; margin-top: 12px; line-height: 1.6; }

        .table-wrapper { overflow-x: auto; border-radius: 12px; }

        table { width: 100%; border-collapse: collapse; min-width: 640px; }

        th {
            background: #0a0f1e;
            color: #8995ad;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: .7px;
            text-align: left;
            padding: 13px 15px;
        }

        th:first-child { border-top-left-radius: 10px; }
        th:last-child { border-top-right-radius: 10px; }

        td { border-top: 1px solid #1a2440; padding: 13px 15px; font-size: 13px; }
        tbody tr:nth-child(even) td { background: rgba(255, 255, 255, .012); }
        tr:hover td { background: #16213b; }

        .symbol { font-weight: 700; color: #fff; }
        .positive { color: #65dfa0; }
        .negative { color: #ff778b; }

        .badge {
            display: inline-block;
            padding: 4px 11px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
            border: 1px solid transparent;
        }

        .badge.stop { background: rgba(255, 119, 139, .12); color: #ff778b; border-color: rgba(255, 119, 139, .25); }
        .badge.target { background: rgba(105, 226, 155, .12); color: #69e29b; border-color: rgba(105, 226, 155, .25); }
        .badge.time { background: rgba(137, 149, 173, .12); color: #8995ad; border-color: rgba(137, 149, 173, .25); }

        pre.log {
            background: #090d19;
            border: 1px solid #202b45;
            border-radius: 12px;
            padding: 16px;
            font-size: 12px;
            line-height: 1.7;
            color: #a9b4cc;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-word;
        }

        .empty { color: #8995ad; font-size: 13px; padding: 12px 0; }
    </style>
</head>
<body>

<header>
    <div class="header-inner">
        <div class="brand">
            <h1>Binance Testnet - Portal de Trade</h1>
            <p>Dinheiro fictício (testnet.binance.vision) - nunca envia ordem real &middot; <a href="index.php">&larr; voltar ao dashboard</a></p>
        </div>
        <div class="status-pill <?= $status['running'] ? 'on' : 'off' ?>">
            <span class="dot"></span>
            <?= $status['running'] ? 'Ativo (pid ' . h((string) $status['pid']) . ')' : 'Desativado' ?>
        </div>
    </div>
</header>

<main>
    <div class="warning">
        Testnet = dado de mercado real, saldo fictício. O loop, quando ativo, roda um ciclo a cada 5
        minutos sozinho (compra/vende de verdade no testnet com sinais reais do scanner). Nenhuma ordem
        real (mainnet) é enviada por este portal.
    </div>

    <?php if ($message !== null): ?>
        <div class="warning <?= $message['type'] === 'ok' ? 'banner-ok' : '' ?>">
            <?= h($message['text']) ?>
        </div>
    <?php endif; ?>

    <div class="top-row">
        <div class="card highlight-card">
            <div class="highlight-top">
                <div>
                    <div class="highlight-label">Resultado acumulado (USDT fictício)</div>
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
                        <span class="highlight-stat-value">
                            <?= $winRate === null ? '-' : number_format($winRate, 0) . '%' ?>
                        </span>
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
            <h2>Valor por posição</h2>
            <form method="post" class="field-row">
                <input type="hidden" name="action" value="save_notional">
                <input
                    type="number"
                    name="notional_usdt"
                    step="0.01"
                    min="<?= MIN_NOTIONAL ?>"
                    max="<?= MAX_NOTIONAL ?>"
                    value="<?= h(number_format($notional, 2, '.', '')) ?>"
                >
                <span>USDT</span>
                <button type="submit" class="btn-save">Salvar</button>
            </form>
            <p class="hint">
                Vale a partir do próximo ciclo. Entre <?= number_format(MIN_NOTIONAL, 0) ?> e
                <?= number_format(MAX_NOTIONAL, 0) ?> USDT, até 5 posições simultâneas.
            </p>
        </div>

        <div class="card">
            <h2>Loop automático</h2>
            <form method="post" class="field-row">
                <?php if ($status['running']): ?>
                    <input type="hidden" name="action" value="stop_loop">
                    <button type="submit" class="btn-deactivate">Desativar</button>
                <?php else: ?>
                    <input type="hidden" name="action" value="start_loop">
                    <button type="submit" class="btn-activate">Ativar</button>
                <?php endif; ?>
            </form>
            <p class="hint">
                Ciclo a cada 5 minutos até você desativar. Ainda testnet, sem dinheiro real.
            </p>
        </div>
    </div>

    <div class="card" style="margin-bottom: 28px;">
        <h2>Posições abertas no testnet (<?= count($openPositions) ?>)</h2>
        <?php if (empty($openPositions)): ?>
            <p class="empty">Nenhuma posição aberta no momento.</p>
        <?php else: ?>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>Símbolo</th>
                            <th>Entrada</th>
                            <th>Preço</th>
                            <th>Quantidade</th>
                            <th>Score</th>
                        </tr>
                    </thead>
                    <tbody>
                        <?php foreach ($openPositions as $pos): ?>
                            <tr>
                                <td class="symbol"><?= h($pos['symbol'] ?? '') ?></td>
                                <td><?= h($pos['entry_time'] ?? '') ?></td>
                                <td><?= h($pos['entry_price'] ?? '') ?></td>
                                <td><?= h($pos['quantity'] ?? '') ?></td>
                                <td><?= h($pos['score'] ?? '') ?></td>
                            </tr>
                        <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
        <?php endif; ?>
    </div>

    <div class="card" style="margin-bottom: 28px;">
        <h2>
            Últimos trades fechados (testnet)
            <?php if (!empty($allTrades)): ?>
                &middot; acumulado:
                <span class="<?= $totalPnl >= 0 ? 'positive' : 'negative' ?>">
                    <?= ($totalPnl >= 0 ? '+' : '') . '$' . number_format($totalPnl, 2, ',', '.') ?>
                </span>
                (fictício)
            <?php endif; ?>
        </h2>
        <?php if (empty($trades)): ?>
            <p class="empty">Nenhum trade fechado ainda.</p>
        <?php else: ?>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>Símbolo</th>
                            <th>Saída</th>
                            <th>Motivo</th>
                            <th>Retorno bruto</th>
                            <th>Ganho/perda (USDT fictício)</th>
                        </tr>
                    </thead>
                    <tbody>
                        <?php foreach ($trades as $trade):
                            $reason = strtolower((string) ($trade['exit_reason'] ?? ''));
                            $ret = (float) ($trade['gross_return_pct'] ?? 0);
                            $pnlRaw = $trade['pnl_usdt'] ?? '';
                            $pnl = $pnlRaw !== '' ? (float) $pnlRaw : null;
                        ?>
                            <tr>
                                <td class="symbol"><?= h($trade['symbol'] ?? '') ?></td>
                                <td><?= h($trade['exit_time'] ?? '') ?></td>
                                <td><span class="badge <?= h($reason) ?>"><?= h($trade['exit_reason'] ?? '') ?></span></td>
                                <td class="<?= $ret >= 0 ? 'positive' : 'negative' ?>">
                                    <?= ($ret >= 0 ? '+' : '') . number_format($ret, 2, ',', '.') ?>%
                                </td>
                                <td class="<?= $pnl === null ? '' : ($pnl >= 0 ? 'positive' : 'negative') ?>">
                                    <?= $pnl === null
                                        ? '-'
                                        : ($pnl >= 0 ? '+' : '') . '$' . number_format($pnl, 2, ',', '.') ?>
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
