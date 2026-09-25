<?php
declare(strict_types=1);

/**
 * CRYPTO RADAR - BIBLIOTECA COMUM DO LIVE (live.php + admin.php)
 *
 * Caminhos, controle do loop, configuração do live (validada contra
 * src/live_config_schema.json - a mesma fonte que o robô lê), histórico de
 * mudanças e login do administrador.
 *
 * Não é uma página: abrir direto no navegador devolve 404.
 */

if (realpath($_SERVER['SCRIPT_FILENAME'] ?? '') === realpath(__FILE__)) {
    http_response_code(404);
    exit;
}

const BASE_DIR        = __DIR__ . '/..';
const PYTHON_BIN      = BASE_DIR . '/.venv/bin/python3';
const LIVE_ENV_FILE   = BASE_DIR . '/.binance-live.env';
const LOOP_SCRIPT     = BASE_DIR . '/src/binance_live_loop.py';
const RESET_SCRIPT    = BASE_DIR . '/src/binance_live_reset.py';
const CB_CLEAR_SCRIPT = BASE_DIR . '/src/binance_live_circuit_breaker_clear.py';
const PID_FILE        = BASE_DIR . '/data/binance_live_loop.pid';
const CONFIG_FILE     = BASE_DIR . '/data/binance_live_config.json';
const CONFIG_HISTORY  = BASE_DIR . '/data/binance_live_config_history.csv';
const SCHEMA_FILE     = BASE_DIR . '/src/live_config_schema.json';
const CB_STATE_FILE   = BASE_DIR . '/data/binance_live_circuit_breaker_state.json';
const OPEN_FILE       = BASE_DIR . '/data/binance_live_open_positions.csv';
const LEDGER_FILE     = BASE_DIR . '/data/binance_live_trades.csv';
const LOG_FILE        = BASE_DIR . '/data/binance_live.log';
const LOOP_LOG        = BASE_DIR . '/data/binance_live_loop_stdout.log';
// Hash da senha do admin (password_hash). Fora de web/ e no .gitignore.
const ADMIN_PASSWORD_FILE = BASE_DIR . '/.admin-password';
const LOGIN_MAX_FAILS     = 5;
const LOGIN_LOCK_SECONDS  = 300;
const SESSION_IDLE_SECONDS = 4 * 3600;

function h(mixed $value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

// ---------------------------------------------------------------- sessão/login

function startAdminSession(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    $dir = sys_get_temp_dir() . '/crypto-radar-sessions';
    if (!is_dir($dir)) {
        @mkdir($dir, 0700, true);
    }
    session_save_path($dir);
    session_name('cradmin');
    session_set_cookie_params(['httponly' => true, 'samesite' => 'Strict', 'path' => '/']);
    session_start();
    if (!empty($_SESSION['admin']) && time() - (int) ($_SESSION['seen'] ?? 0) > SESSION_IDLE_SECONDS) {
        $_SESSION = [];
    }
    if (!empty($_SESSION['admin'])) {
        $_SESSION['seen'] = time();
    }
    if (empty($_SESSION['csrf'])) {
        $_SESSION['csrf'] = bin2hex(random_bytes(16));
    }
}

function isAdmin(): bool
{
    startAdminSession();
    return !empty($_SESSION['admin']);
}

function csrfToken(): string
{
    startAdminSession();
    return (string) $_SESSION['csrf'];
}

function csrfField(): string
{
    return '<input type="hidden" name="csrf" value="' . h(csrfToken()) . '">';
}

function csrfValid(): bool
{
    startAdminSession();
    return hash_equals((string) $_SESSION['csrf'], (string) ($_POST['csrf'] ?? ''));
}

/** Estado das tentativas de login (arquivo fora de web/, por máquina). */
function loginThrottleFile(): string
{
    return sys_get_temp_dir() . '/crypto-radar-admin-login.json';
}

function loginLockedFor(): int
{
    $s = json_decode((string) @file_get_contents(loginThrottleFile()), true) ?: [];
    $until = (int) ($s['locked_until'] ?? 0);
    return max(0, $until - time());
}

function attemptLogin(string $password): array
{
    startAdminSession();
    if (($left = loginLockedFor()) > 0) {
        return ['ok' => false, 'text' => "Muitas tentativas erradas. Tente de novo em {$left}s."];
    }
    $hash = trim((string) @file_get_contents(ADMIN_PASSWORD_FILE));
    if ($hash === '') {
        return ['ok' => false, 'text' => 'Senha do admin não configurada (arquivo .admin-password ausente).'];
    }
    $s = json_decode((string) @file_get_contents(loginThrottleFile()), true) ?: [];
    if (password_verify($password, $hash)) {
        @file_put_contents(loginThrottleFile(), json_encode(['fails' => 0]));
        session_regenerate_id(true);
        $_SESSION['admin'] = true;
        $_SESSION['seen'] = time();
        $_SESSION['csrf'] = bin2hex(random_bytes(16));
        return ['ok' => true, 'text' => 'Login feito.'];
    }
    usleep(800000);
    $fails = (int) ($s['fails'] ?? 0) + 1;
    $s = ['fails' => $fails];
    if ($fails >= LOGIN_MAX_FAILS) {
        $s = ['fails' => 0, 'locked_until' => time() + LOGIN_LOCK_SECONDS];
    }
    @file_put_contents(loginThrottleFile(), json_encode($s));
    return ['ok' => false, 'text' => 'Senha incorreta.'];
}

function logoutAdmin(): void
{
    startAdminSession();
    $_SESSION = [];
    session_regenerate_id(true);
}

function changeAdminPassword(string $current, string $new): array
{
    $hash = trim((string) @file_get_contents(ADMIN_PASSWORD_FILE));
    if ($hash === '' || !password_verify($current, $hash)) {
        return ['ok' => false, 'text' => 'Senha atual incorreta.'];
    }
    if (strlen($new) < 8) {
        return ['ok' => false, 'text' => 'A nova senha precisa ter pelo menos 8 caracteres.'];
    }
    $tmp = ADMIN_PASSWORD_FILE . '.tmp';
    file_put_contents($tmp, password_hash($new, PASSWORD_DEFAULT) . "\n");
    @chmod($tmp, 0600);
    rename($tmp, ADMIN_PASSWORD_FILE);
    return ['ok' => true, 'text' => 'Senha alterada.'];
}

// ---------------------------------------------------------------- configuração

function configSchema(): array
{
    static $schema = null;
    if ($schema === null) {
        $schema = json_decode((string) file_get_contents(SCHEMA_FILE), true) ?: ['groups' => []];
    }
    return $schema;
}

/** @return array<string, array> campos do schema indexados pela chave */
function configFields(): array
{
    $out = [];
    foreach (configSchema()['groups'] as $g) {
        foreach ($g['fields'] as $f) {
            $out[$f['key']] = $f;
        }
    }
    return $out;
}

/** Mesma regra do robô (_coerce): valor válido ou o default. */
function coerceField(array $f, mixed $value): mixed
{
    if ($value === null) {
        $value = $f['default'];
        if ($f['type'] !== 'list') {
            return $value;
        }
    }
    switch ($f['type']) {
        case 'bool':
            return is_bool($value) ? $value : $f['default'];
        case 'list':
            if (is_string($value)) {
                $value = explode(',', $value);
            }
            if (!is_array($value)) {
                return $f['default'];
            }
            $items = array_values(array_unique(array_filter(array_map(
                static fn($v) => strtoupper(trim((string) $v)), $value
            ), static fn($v) => $v !== '')));
            sort($items);
            return $items;
        default:
            if (!is_numeric($value)) {
                return $f['default'];
            }
            $v = (float) $value;
            if ($v < $f['min'] || $v > $f['max']) {
                return $f['default'];
            }
            return $f['type'] === 'int' ? (int) $v : $v;
    }
}

function rawConfig(): array
{
    $raw = json_decode((string) @file_get_contents(CONFIG_FILE), true);
    return is_array($raw) ? $raw : [];
}

function loadLiveConfig(): array
{
    $raw = rawConfig();
    $cfg = [];
    foreach (configFields() as $key => $f) {
        $cfg[$key] = coerceField($f, $raw[$key] ?? null);
    }
    return $cfg;
}

/**
 * Valida o valor enviado pelo formulário. Retorna [ok, valor, erro].
 * Diferente de coerceField: aqui valor fora da faixa é ERRO (não vira
 * default em silêncio).
 */
function validateInput(array $f, mixed $input): array
{
    if ($f['type'] === 'bool') {
        return [true, $input === 'on' || $input === '1' || $input === true, null];
    }
    if ($f['type'] === 'list') {
        return [true, coerceField($f, (string) $input), null];
    }
    $s = str_replace(',', '.', trim((string) $input));
    if ($s === '' || !is_numeric($s)) {
        return [false, null, "{$f['label']}: valor inválido"];
    }
    $v = (float) $s;
    if ($v < $f['min'] || $v > $f['max']) {
        return [false, null, sprintf('%s: use entre %s e %s', $f['label'], fmtNum($f['min']), fmtNum($f['max']))];
    }
    if ($f['type'] === 'int' && floor($v) != $v) {
        return [false, null, "{$f['label']}: use um número inteiro"];
    }
    return [true, $f['type'] === 'int' ? (int) $v : $v, null];
}

function fmtNum(mixed $v): string
{
    if (is_bool($v)) {
        return $v ? 'sim' : 'não';
    }
    if (is_array($v)) {
        return implode(', ', $v);
    }
    $s = rtrim(rtrim(number_format((float) $v, 6, ',', '.'), '0'), ',');
    return $s === '' || $s === '-' ? '0' : $s;
}

/**
 * Grava só as chaves alteradas (preserva o resto do arquivo) e registra cada
 * mudança em data/binance_live_config_history.csv. Retorna as mudanças.
 */
function saveLiveConfig(array $changes, string $source): array
{
    $raw = rawConfig();
    $current = loadLiveConfig();
    $changed = [];
    foreach ($changes as $key => $value) {
        if (!array_key_exists($key, $current) || $current[$key] == $value) {
            continue;
        }
        $changed[] = [$key, $current[$key], $value];
        $raw[$key] = $value;
    }
    if (!$changed) {
        return [];
    }
    $tmp = CONFIG_FILE . '.tmp';
    file_put_contents($tmp, json_encode($raw, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . "\n");
    rename($tmp, CONFIG_FILE);

    $isNew = !file_exists(CONFIG_HISTORY);
    $fh = fopen(CONFIG_HISTORY, 'a');
    if ($isNew) {
        fputcsv($fh, ['timestamp', 'key', 'old', 'new', 'source'], ',', '"', '');
    }
    $now = (new DateTimeImmutable('now', new DateTimeZone('UTC')))->format(DATE_ATOM);
    foreach ($changed as [$key, $old, $new]) {
        fputcsv($fh, [$now, $key, fmtNum($old), fmtNum($new), $source], ',', '"', '');
    }
    fclose($fh);
    return $changed;
}

function configHistory(int $limit = 50): array
{
    if (!file_exists(CONFIG_HISTORY)) {
        return [];
    }
    $rows = [];
    $fh = fopen(CONFIG_HISTORY, 'r');
    $header = fgetcsv($fh, 0, ',', '"', '');
    while (($r = fgetcsv($fh, 0, ',', '"', '')) !== false) {
        if (count($r) === count($header)) {
            $rows[] = array_combine($header, $r);
        }
    }
    fclose($fh);
    return array_slice(array_reverse($rows), 0, $limit);
}

// ---------------------------------------------------------------- loop / ações

function liveEnvConfigured(): bool
{
    return file_exists(LIVE_ENV_FILE);
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
    $cmd = 'cd ' . escapeshellarg(BASE_DIR) . ' && nohup ' . escapeshellarg(PYTHON_BIN) . ' '
        . escapeshellarg(LOOP_SCRIPT) . ' >> ' . escapeshellarg(LOOP_LOG) . ' 2>&1 & echo $!';
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
    return runPython(RESET_SCRIPT);
}

function clearCircuitBreaker(): array
{
    return runPython(CB_CLEAR_SCRIPT, ['portal']);
}

function runPython(string $script, array $args = []): array
{
    $cmd = 'cd ' . escapeshellarg(BASE_DIR) . ' && ' . escapeshellarg(PYTHON_BIN) . ' ' . escapeshellarg($script);
    foreach ($args as $a) {
        $cmd .= ' ' . escapeshellarg($a);
    }
    exec($cmd . ' 2>&1', $output, $exitCode);
    return ['ok' => $exitCode === 0, 'output' => implode("\n", $output)];
}

// ---------------------------------------------------------------- versões (git)

function gitRun(array $args, string $dir = BASE_DIR, int $timeout = 20): array
{
    $cmd = 'timeout ' . $timeout . ' git -C ' . escapeshellarg($dir);
    foreach ($args as $a) {
        $cmd .= ' ' . escapeshellarg($a);
    }
    exec($cmd . ' 2>&1', $out, $code);
    return [$code, implode("\n", $out)];
}

/** SHA do main no GitHub (consulta de rede; guardado 60s na sessão). */
function gitRemoteHead(string $dir = BASE_DIR): ?string
{
    startAdminSession();
    $cache = $_SESSION['git_remote'][$dir] ?? null;
    if ($cache && time() - $cache['at'] < 60) {
        return $cache['sha'];
    }
    [$code, $out] = gitRun(['ls-remote', 'origin', 'refs/heads/main'], $dir, 10);
    $sha = ($code === 0 && preg_match('/^([0-9a-f]{40})/', $out, $m)) ? $m[1] : null;
    $_SESSION['git_remote'][$dir] = ['sha' => $sha, 'at' => time()];
    return $sha;
}

/**
 * Versões (commits) das últimas $hours horas no main local, com:
 * pushed = já está no GitHub; reverted_by = versão que já desfez esta.
 */
function gitRecentCommits(int $hours = 24, string $dir = BASE_DIR): array
{
    [$code, $out] = gitRun(['log', '--since=' . $hours . ' hours ago', '--format=%H%x1f%cI%x1f%s%x1f%P%x1f%b%x1e'], $dir);
    if ($code !== 0 || trim($out) === '') {
        return [];
    }
    $remote = gitRemoteHead($dir);
    $commits = [];
    foreach (array_filter(array_map('trim', explode("\x1e", $out))) as $rec) {
        [$sha, $date, $subject, $parents, $body] = array_pad(explode("\x1f", $rec), 5, '');
        $commits[$sha] = [
            'sha' => $sha, 'short' => substr($sha, 0, 7), 'date' => $date, 'subject' => $subject,
            'merge' => str_contains(trim($parents), ' '), 'body' => $body,
            'pushed' => $remote !== null && gitRun(['merge-base', '--is-ancestor', $sha, $remote], $dir)[0] === 0,
            'reverted_by' => null, 'files' => [],
        ];
    }
    foreach ($commits as $sha => $c) {
        if (preg_match('/Desfaz ([0-9a-f]{40})|This reverts commit ([0-9a-f]{40})/', $c['body'], $m)) {
            $target = $m[1] !== '' ? $m[1] : $m[2];
            if (isset($commits[$target])) {
                $commits[$target]['reverted_by'] = $c['short'];
            }
        }
        [, $files] = gitRun(['show', '--name-only', '--format=', $sha], $dir);
        $commits[$sha]['files'] = array_values(array_filter(explode("\n", trim($files))));
    }
    return array_values($commits);
}

/**
 * Volta (desfaz) uma versão com `git revert`: cria uma versão nova que
 * desfaz a escolhida, sem reescrever o histórico. Recusa se houver algo já
 * preparado pra commit, se algum arquivo da versão tiver alteração local não
 * salva, ou se der conflito (nesse caso desiste e deixa tudo como estava).
 */
function gitRevertCommit(string $sha, string $dir = BASE_DIR): array
{
    if (!preg_match('/^[0-9a-f]{40}$/', $sha)) {
        return ['ok' => false, 'text' => 'Versão inválida.'];
    }
    $commit = null;
    foreach (gitRecentCommits(24 * 7, $dir) as $c) {
        if ($c['sha'] === $sha) {
            $commit = $c;
        }
    }
    if ($commit === null) {
        return ['ok' => false, 'text' => 'Versão não encontrada entre as recentes.'];
    }
    if ($commit['merge']) {
        return ['ok' => false, 'text' => 'Versão de merge não pode ser desfeita por aqui.'];
    }
    if ($commit['reverted_by']) {
        return ['ok' => false, 'text' => "Essa versão já foi desfeita por {$commit['reverted_by']}."];
    }
    if (gitRun(['diff', '--cached', '--quiet'], $dir)[0] !== 0) {
        return ['ok' => false, 'text' => 'Há alterações já preparadas pra commit (git add) - resolva no terminal antes.'];
    }
    [, $dirty] = gitRun(array_merge(['status', '--porcelain', '--'], $commit['files']), $dir);
    if (trim($dirty) !== '') {
        $lines = array_filter(explode("\n", rtrim($dirty)), static fn($l) => trim($l) !== '');
        return ['ok' => false, 'text' => 'Arquivos dessa versão têm alterações locais não salvas: '
            . implode(', ', array_map(static fn($l) => substr($l, 3), $lines))
            . '. Faça o commit delas antes (ou descarte no terminal).'];
    }
    [$code, $out] = gitRun(['revert', '--no-commit', $sha], $dir);
    if ($code !== 0) {
        gitRun(['revert', '--abort'], $dir);
        return ['ok' => false, 'text' => 'Não deu pra desfazer sem conflito com versões posteriores - nada foi alterado.', 'output' => $out];
    }
    $msg = "Volta: {$commit['subject']}\n\nDesfaz {$sha} (feito pelo Admin do portal).";
    [$code, $out2] = gitRun(['commit', '-m', $msg], $dir);
    if ($code !== 0) {
        gitRun(['revert', '--abort'], $dir);
        return ['ok' => false, 'text' => 'Falha ao gravar a versão de volta - nada foi alterado.', 'output' => $out2];
    }
    [, $newSha] = gitRun(['rev-parse', '--short', 'HEAD'], $dir);
    $touchesPython = (bool) array_filter($commit['files'], static fn($f) => str_starts_with($f, 'src/'));
    return ['ok' => true, 'new' => trim($newSha), 'python' => $touchesPython,
        'text' => "Versão {$commit['short']} desfeita pela nova versão " . trim($newSha) . '.'];
}
