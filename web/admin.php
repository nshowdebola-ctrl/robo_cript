<?php
declare(strict_types=1);

/**
 * CRYPTO RADAR - ADMIN DO LIVE (DINHEIRO REAL)
 *
 * Todos os ajustes do robô (src/live_config_schema.json), operação do loop,
 * status da chave da Binance (só leitura) e histórico de mudanças. Exige
 * login; a senha fica só como hash em .admin-password (fora de web/, fora
 * do git). Mudança de configuração vale no próximo ciclo do loop (~1 min),
 * sem reiniciar.
 */

require __DIR__ . '/lib_live.php';

const DUST_SCRIPT       = BASE_DIR . '/src/binance_live_dust_sweeper.py';
const REVIEW_SCRIPT     = BASE_DIR . '/src/weekly_review.py';
const KEY_STATUS_SCRIPT = BASE_DIR . '/src/binance_live_key_status.py';

startAdminSession();
$message = null;
$output = null;       // saída de script pra mostrar na página
$keyStatus = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = (string) ($_POST['action'] ?? '');
    if (!csrfValid()) {
        $message = ['type' => 'error', 'text' => 'Sessão expirada - recarregue a página e tente de novo.'];
    } elseif ($action === 'login') {
        $r = attemptLogin((string) ($_POST['password'] ?? ''));
        if ($r['ok']) {
            header('Location: admin.php');
            exit;
        }
        $message = ['type' => 'error', 'text' => $r['text']];
    } elseif (!isAdmin()) {
        $message = ['type' => 'error', 'text' => 'Faça login primeiro.'];
    } elseif ($action === 'logout') {
        logoutAdmin();
        header('Location: admin.php');
        exit;
    } elseif ($action === 'save_config') {
        $changes = [];
        $errors = [];
        $current = loadLiveConfig();
        $strategyChanged = [];
        foreach (configFields() as $key => $f) {
            $input = $f['type'] === 'bool' ? (isset($_POST[$key]) ? 'on' : 'off') : ($_POST[$key] ?? null);
            if ($input === null) {
                continue;
            }
            [$ok, $value, $err] = validateInput($f, $input);
            if (!$ok) {
                $errors[] = $err;
                continue;
            }
            $changes[$key] = $value;
            if (!empty($f['strategy']) && $current[$key] != $value) {
                $strategyChanged[] = $f['label'];
            }
        }
        if ($errors) {
            $message = ['type' => 'error', 'text' => 'Nada foi salvo. ' . implode(' | ', $errors)];
        } elseif ($strategyChanged && ($_POST['confirm_strategy'] ?? '') !== 'on') {
            $message = ['type' => 'error', 'text' => 'Nada foi salvo. Você alterou ajuste(s) de estratégia ('
                . implode(', ', $strategyChanged) . ') - marque a confirmação no fim do formulário.'];
        } else {
            $changed = saveLiveConfig($changes, 'admin.php');
            $fields = configFields();
            $message = ['type' => 'ok', 'text' => $changed
                ? 'Salvo (vale no próximo ciclo do loop): ' . implode('; ', array_map(
                    static fn($c) => $fields[$c[0]]['label'] . ': ' . fmtNum($c[1]) . ' → ' . fmtNum($c[2]), $changed))
                : 'Nada mudou.'];
        }
    } elseif ($action === 'start_loop') {
        if (!liveEnvConfigured()) {
            $message = ['type' => 'error', 'text' => 'Chave real não configurada (.binance-live.env não existe).'];
        } else {
            startLoop();
            $message = ['type' => 'ok', 'text' => 'Loop iniciado.'];
        }
    } elseif ($action === 'stop_loop') {
        stopLoop();
        $message = ['type' => 'ok', 'text' => 'Loop parado. Posições abertas NÃO são vendidas enquanto ele estiver parado.'];
    } elseif ($action === 'restart_loop') {
        stopLoop();
        startLoop();
        $message = ['type' => 'ok', 'text' => 'Loop reiniciado.'];
    } elseif ($action === 'reset_all') {
        if (($_POST['confirm'] ?? '') !== 'VENDER') {
            $message = ['type' => 'error', 'text' => 'Confirmação incorreta - digite VENDER pra vender tudo.'];
        } else {
            $r = resetAll();
            $message = $r['ok']
                ? ['type' => 'ok', 'text' => 'Posições vendidas pra USDT. Loop ficou desativado.']
                : ['type' => 'error', 'text' => 'Venda terminou com erro.'];
            $output = $r['output'];
        }
    } elseif ($action === 'clear_circuit_breaker') {
        if (($_POST['confirm_cb'] ?? '') !== 'on') {
            $message = ['type' => 'error', 'text' => 'Marque a confirmação pra reativar o circuit breaker.'];
        } else {
            $r = clearCircuitBreaker();
            $message = ['type' => $r['ok'] ? 'ok' : 'error', 'text' => $r['ok'] ? 'Circuit breaker reativado.' : 'Falha ao reativar.'];
            $output = $r['output'];
        }
    } elseif ($action === 'run_dust') {
        if (($_POST['confirm_dust'] ?? '') !== 'on') {
            $message = ['type' => 'error', 'text' => 'Marque a confirmação: a varredura envia ordens reais.'];
        } else {
            $r = runPython(DUST_SCRIPT);
            $message = ['type' => $r['ok'] ? 'ok' : 'error', 'text' => 'Varredura de sobras executada.'];
            $output = $r['output'];
        }
    } elseif ($action === 'preview_review') {
        $r = runPython(REVIEW_SCRIPT, ['--print']);
        $message = ['type' => $r['ok'] ? 'ok' : 'error', 'text' => 'Prévia da revisão semanal (não enviada).'];
        $output = $r['output'];
    } elseif ($action === 'key_status') {
        $r = runPython(KEY_STATUS_SCRIPT);
        $lines = explode("\n", trim($r['output']));
        $keyStatus = json_decode((string) end($lines), true);
        if (!is_array($keyStatus)) {
            $message = ['type' => 'error', 'text' => 'Não consegui ler o status da chave.'];
            $output = $r['output'];
        }
    } elseif ($action === 'git_revert') {
        if (($_POST['confirm_revert'] ?? '') !== 'on') {
            $message = ['type' => 'error', 'text' => 'Marque a confirmação pra voltar a versão.'];
        } else {
            $r = gitRevertCommit((string) ($_POST['sha'] ?? ''));
            $text = $r['text'];
            if ($r['ok']) {
                if (!empty($r['python']) && ($_POST['restart'] ?? '') === 'on' && loopStatus()['running']) {
                    stopLoop();
                    startLoop();
                    $text .= ' Loop reiniciado com o código desfeito.';
                } elseif (!empty($r['python'])) {
                    $text .= ' A versão mexia no robô (src/): reinicie o loop pra valer.';
                }
                $text .= ' Pra levar ao GitHub, rode ./push.sh no terminal.';
            }
            $message = ['type' => $r['ok'] ? 'ok' : 'error', 'text' => $text];
            $output = $r['output'] ?? null;
        }
    } elseif ($action === 'change_password') {
        $new = (string) ($_POST['new_password'] ?? '');
        if ($new !== (string) ($_POST['new_password2'] ?? '')) {
            $message = ['type' => 'error', 'text' => 'A confirmação da nova senha não confere.'];
        } else {
            $r = changeAdminPassword((string) ($_POST['current_password'] ?? ''), $new);
            $message = ['type' => $r['ok'] ? 'ok' : 'error', 'text' => $r['text']];
        }
    }
}

$logged = isAdmin();
$status = loopStatus();
$config = loadLiveConfig();
$cbState = loadCbState();
$history = $logged ? configHistory(40) : [];
$commits = $logged ? gitRecentCommits(24) : [];
$remoteHead = $logged ? gitRemoteHead() : null;

function fieldInput(array $f, mixed $value): string
{
    $key = h($f['key']);
    if ($f['type'] === 'bool') {
        return '<label class="switch"><input type="checkbox" name="' . $key . '"' . ($value ? ' checked' : '') . '> <span>ligado</span></label>';
    }
    if ($f['type'] === 'list') {
        return '<textarea name="' . $key . '" rows="2">' . h(implode(', ', $value)) . '</textarea>';
    }
    return '<input type="text" inputmode="decimal" name="' . $key . '" value="' . h(fmtNum($value)) . '">'
        . (isset($f['unit']) ? ' <span class="unit">' . h($f['unit']) . '</span>' : '');
}

function statusRow(string $label, ?bool $good, string $text): string
{
    $cls = $good === null ? '' : ($good ? 'ok' : 'bad');
    return '<tr><td>' . h($label) . '</td><td class="' . $cls . '">' . h($text) . '</td></tr>';
}
?>
<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Radar Admin</title>
    <style>
        :root {
            --bg: #120b0b; --card: #1c1212; --border: #3d2525; --text: #f2e9e9; --muted: #b08a8a;
            --accent: #c94a4a; --ok: #65dfa0; --bad: #ff778b; --warn: #ffd27a; --field: #150a0a;
        }
        * { box-sizing: border-box; }
        body { margin: 0; font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
        header { background: #1a0f0f; border-bottom: 1px solid var(--border); padding: 18px 24px; }
        header .inner, main { max-width: 1100px; margin: 0 auto; }
        header h1 { margin: 0; font-size: 22px; }
        header p { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
        header a { color: var(--muted); }
        main { padding: 24px 16px 60px; }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 20px; margin-bottom: 20px; }
        .card h2 { margin: 0 0 14px; font-size: 13px; text-transform: uppercase; letter-spacing: .6px; color: #dcb8b8; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .field { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 12px; align-items: center; padding: 10px 0; border-top: 1px solid #2a1a1a; }
        .field:first-of-type { border-top: 0; }
        .field label.name { font-size: 14px; }
        .field .help { grid-column: 1 / -1; font-size: 12px; color: var(--muted); line-height: 1.5; }
        .field .range { font-size: 11px; color: #8a6a6a; }
        .strategy-tag { font-size: 10px; color: var(--warn); border: 1px solid #7a5a1f; border-radius: 999px; padding: 1px 6px; margin-left: 6px; }
        input[type=text], input[type=password], textarea { background: var(--field); border: 1px solid #4a2525; color: var(--text); padding: 9px 11px; border-radius: 8px; font-size: 14px; font-family: inherit; }
        input[type=text] { width: 110px; text-align: right; }
        textarea { width: 100%; grid-column: 1 / -1; resize: vertical; }
        .unit { color: var(--muted); font-size: 12px; }
        .switch { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted); }
        button { font-family: inherit; font-size: 14px; font-weight: 700; padding: 10px 18px; border-radius: 8px; border: 0; cursor: pointer; color: #fff; background: #5a3a3a; }
        button.primary { background: linear-gradient(135deg, #c94a4a, #8f1f1f); }
        button.go { background: linear-gradient(135deg, #29c073, #1a8f52); }
        button.danger { background: linear-gradient(135deg, #e0495f, #a5293a); }
        .row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin: 8px 0; }
        .banner { padding: 12px 16px; border-radius: 10px; margin-bottom: 18px; font-size: 14px; line-height: 1.5; }
        .banner.ok { background: #12351f; border: 1px solid #245a35; color: #b8f5d0; }
        .banner.error { background: #3a0d13; border: 1px solid #7a1f28; color: #ffb3b3; }
        .hint { color: var(--muted); font-size: 12px; line-height: 1.6; margin: 8px 0 0; }
        pre { background: #0d0707; border: 1px solid var(--border); border-radius: 10px; padding: 14px; font-size: 12px; white-space: pre-wrap; word-break: break-word; color: #e6cccc; max-height: 420px; overflow: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { text-align: left; padding: 8px 6px; border-top: 1px solid #2a1a1a; vertical-align: top; }
        th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .5px; border-top: 0; }
        td.ok { color: var(--ok); font-weight: 600; } td.bad { color: var(--bad); font-weight: 600; }
        .pill { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }
        .pill.on { background: rgba(101,223,160,.12); color: var(--ok); } .pill.off { background: rgba(255,119,139,.12); color: var(--bad); }
        .login { max-width: 360px; margin: 60px auto; }
        .confirm { margin-top: 14px; padding: 12px; border: 1px dashed #7a5a1f; border-radius: 10px; font-size: 13px; color: var(--warn); }
        @media (max-width: 600px) { .field { grid-template-columns: 1fr; } input[type=text] { width: 100%; text-align: left; } }
    </style>
</head>
<body>
<header>
    <div class="inner">
        <h1>Crypto Radar · Admin do live</h1>
        <p>DINHEIRO REAL · <a href="live.php">painel live</a> · <a href="index.php">dashboard</a>
            <?php if ($logged): ?> · loop <span class="pill <?= $status['running'] ? 'on' : 'off' ?>"><?= $status['running'] ? 'rodando (pid ' . h($status['pid']) . ')' : 'parado' ?></span><?php endif; ?>
        </p>
    </div>
</header>
<main>
    <?php if ($message): ?>
        <div class="banner <?= $message['type'] === 'ok' ? 'ok' : 'error' ?>"><?= h($message['text']) ?></div>
    <?php endif; ?>

<?php if (!$logged): ?>
    <div class="card login">
        <h2>Login</h2>
        <form method="post">
            <?= csrfField() ?>
            <input type="hidden" name="action" value="login">
            <div class="row"><input type="password" name="password" placeholder="Senha" autofocus required style="width:100%"></div>
            <div class="row"><button class="primary" type="submit">Entrar</button></div>
        </form>
        <p class="hint">Após <?= LOGIN_MAX_FAILS ?> tentativas erradas, bloqueia por <?= LOGIN_LOCK_SECONDS / 60 ?> minutos.</p>
    </div>
<?php else: ?>

    <?php if ($output !== null): ?>
        <div class="card"><h2>Resultado</h2><pre><?= h($output) ?></pre></div>
    <?php endif; ?>

    <form method="post" class="card">
        <?= csrfField() ?>
        <input type="hidden" name="action" value="save_config">
        <h2>Configuração do robô <span class="hint" style="text-transform:none;letter-spacing:0">vale no próximo ciclo (~1 min), sem reiniciar</span></h2>
        <div class="grid">
            <?php foreach (configSchema()['groups'] as $g): ?>
                <div>
                    <h2 style="margin-top:6px"><?= h($g['title']) ?></h2>
                    <?php foreach ($g['fields'] as $f): ?>
                        <div class="field">
                            <label class="name"><?= h($f['label']) ?><?php if (!empty($f['strategy'])): ?><span class="strategy-tag">estratégia</span><?php endif; ?>
                                <?php if (in_array($f['type'], ['float', 'int'], true)): ?>
                                    <br><span class="range">faixa <?= h(fmtNum($f['min'])) ?> a <?= h(fmtNum($f['max'])) ?> · padrão <?= h(fmtNum($f['default'])) ?></span>
                                <?php endif; ?>
                            </label>
                            <?php if ($f['type'] !== 'list'): ?><div><?= fieldInput($f, $config[$f['key']]) ?></div><?php else: ?><?= fieldInput($f, $config[$f['key']]) ?><?php endif; ?>
                            <?php if (!empty($f['help'])): ?><div class="help"><?= h($f['help']) ?></div><?php endif; ?>
                        </div>
                    <?php endforeach; ?>
                </div>
            <?php endforeach; ?>
        </div>
        <div class="confirm">
            <label><input type="checkbox" name="confirm_strategy">
                Confirmo mudança em ajuste marcado como <b>estratégia</b> (stop, alvo, tempo, meta). Os valores atuais foram os melhores nos testes; mudar no meio da avaliação dificulta saber o que funcionou.</label>
        </div>
        <div class="row" style="margin-top:14px"><button class="primary" type="submit">Salvar configuração</button></div>
    </form>

    <div class="grid">
        <div class="card">
            <h2>Loop</h2>
            <p class="hint" style="margin-top:0">Estado: <span class="pill <?= $status['running'] ? 'on' : 'off' ?>"><?= $status['running'] ? 'rodando' : 'parado' ?></span>
                · circuit breaker: <b><?= $cbState['tripped'] ? 'ACIONADO' : 'normal' ?></b></p>
            <div class="row">
                <?php foreach ($status['running'] ? ['stop_loop' => 'Parar', 'restart_loop' => 'Reiniciar'] : ['start_loop' => 'Iniciar'] as $act => $label): ?>
                    <form method="post"><?= csrfField() ?><input type="hidden" name="action" value="<?= $act ?>"><button class="<?= $act === 'start_loop' ? 'go' : '' ?>" type="submit"><?= $label ?></button></form>
                <?php endforeach; ?>
            </div>
            <p class="hint">Reiniciar só é preciso depois de mudança no código. Mudança de configuração vale sozinha no próximo ciclo.</p>
            <?php if ($cbState['tripped']): ?>
                <form method="post" style="margin-top:12px"><?= csrfField() ?><input type="hidden" name="action" value="clear_circuit_breaker">
                    <label class="hint"><input type="checkbox" name="confirm_cb"> Entendo que isso libera abertura de posições reais.</label>
                    <div class="row"><button type="submit">Reativar circuit breaker</button></div>
                </form>
            <?php endif; ?>
        </div>

        <div class="card">
            <h2>Chave da Binance (só leitura)</h2>
            <?php if ($keyStatus): ?>
                <table>
                    <?php if (!empty($keyStatus['ok'])): ?>
                        <?= statusRow('Chave em uso', null, (string) ($keyStatus['key_hint'] ?? '-')) ?>
                        <?= statusRow('Autentica', true, 'sim') ?>
                        <?= statusRow('Saque', !$keyStatus['enable_withdrawals'], $keyStatus['enable_withdrawals'] ? 'LIGADO - desligue na Binance' : 'desligado') ?>
                        <?= statusRow('Restrição de IP', $keyStatus['ip_restrict'], $keyStatus['ip_restrict'] ? 'ativa' : 'SEM restrição - ative na Binance') ?>
                        <?= statusRow('Trade spot', null, $keyStatus['enable_spot_trading'] ? 'ligado' : 'desligado') ?>
                        <?= statusRow('Futuros', !$keyStatus['enable_futures'], $keyStatus['enable_futures'] ? 'LIGADO (não usado)' : 'desligado') ?>
                        <?= statusRow('Criada em', null, $keyStatus['created_at'] ? (new DateTimeImmutable($keyStatus['created_at']))->setTimezone(new DateTimeZone('America/Sao_Paulo'))->format('d/m/Y H:i') : '-') ?>
                        <?= statusRow('IP público desta máquina', null, (string) ($keyStatus['public_ip'] ?? '-')) ?>
                    <?php else: ?>
                        <?= statusRow('Autentica', false, (string) ($keyStatus['error'] ?? 'erro')) ?>
                        <?= statusRow('IP público desta máquina', null, (string) ($keyStatus['public_ip'] ?? '-')) ?>
                    <?php endif; ?>
                </table>
            <?php endif; ?>
            <form method="post" class="row"><?= csrfField() ?><input type="hidden" name="action" value="key_status"><button type="submit">Verificar agora</button></form>
            <p class="hint">A troca da chave é feita no terminal (nunca pelo portal). Se a chave foi exposta, crie uma nova na Binance com saque desligado e restrição de IP, e apague a antiga.</p>
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <h2>Rodar agora</h2>
            <form method="post"><?= csrfField() ?><input type="hidden" name="action" value="run_dust">
                <label class="hint"><input type="checkbox" name="confirm_dust"> Varredura de sobras envia ordens reais (vende/converte restos).</label>
                <div class="row"><button type="submit">Varredura de sobras</button></div>
            </form>
            <form method="post" style="margin-top:12px"><?= csrfField() ?><input type="hidden" name="action" value="preview_review">
                <div class="row"><button type="submit">Prévia da revisão semanal</button></div>
            </form>
            <p class="hint">A prévia só mostra aqui, não envia no Telegram. O envio automático segue toda segunda 08:00.</p>
        </div>

        <div class="card">
            <h2>Vender tudo (emergência)</h2>
            <form method="post" onsubmit="return this.confirm.value === 'VENDER';"><?= csrfField() ?><input type="hidden" name="action" value="reset_all">
                <div class="row"><input type="text" name="confirm" placeholder="Digite VENDER" autocomplete="off" style="width:160px;text-align:left"><button class="danger" type="submit">Vender tudo</button></div>
            </form>
            <p class="hint">Para o loop e vende todas as posições pra USDT. Histórico e circuit breaker são preservados.</p>
        </div>
    </div>

    <div class="card">
        <h2>Versões das últimas 24h (git)</h2>
        <?php if ($remoteHead === null): ?>
            <p class="hint" style="margin-top:0">Não consegui consultar o GitHub agora - a coluna "GitHub" pode estar incompleta.</p>
        <?php endif; ?>
        <?php if (!$commits): ?>
            <p class="hint">Nenhuma versão nas últimas 24h.</p>
        <?php else: ?>
            <table>
                <tr><th>Quando (Brasília)</th><th>Versão</th><th>Descrição</th><th>GitHub</th><th></th></tr>
                <?php foreach ($commits as $c): ?>
                    <tr>
                        <td><?= h((new DateTimeImmutable($c['date']))->setTimezone(new DateTimeZone('America/Sao_Paulo'))->format('d/m H:i')) ?></td>
                        <td><code><?= h($c['short']) ?></code></td>
                        <td><?= h($c['subject']) ?><br><span class="range"><?= count($c['files']) ?> arquivo(s)<?= array_filter($c['files'], static fn($f) => str_starts_with($f, 'src/')) ? ' · mexe no robô' : '' ?></span></td>
                        <td class="<?= $c['pushed'] ? 'ok' : '' ?>"><?= $c['pushed'] ? 'enviada' : 'só local' ?></td>
                        <td>
                            <?php if ($c['reverted_by']): ?>
                                <span class="range">desfeita por <?= h($c['reverted_by']) ?></span>
                            <?php elseif (!$c['merge']): ?>
                                <form method="post" onsubmit="return confirm('Voltar (desfazer) a versão <?= h($c['short']) ?>?');">
                                    <?= csrfField() ?><input type="hidden" name="action" value="git_revert"><input type="hidden" name="sha" value="<?= h($c['sha']) ?>">
                                    <label class="range"><input type="checkbox" name="confirm_revert"> confirmo</label>
                                    <?php if (array_filter($c['files'], static fn($f) => str_starts_with($f, 'src/'))): ?>
                                        <label class="range"><input type="checkbox" name="restart" checked> reiniciar loop</label>
                                    <?php endif; ?>
                                    <button type="submit">Voltar</button>
                                </form>
                            <?php endif; ?>
                        </td>
                    </tr>
                <?php endforeach; ?>
            </table>
        <?php endif; ?>
        <p class="hint">"Voltar" cria uma versão nova que desfaz a escolhida (git revert) - nada é apagado do histórico e dá pra voltar a volta.
            Se conflitar com versões posteriores, nada é alterado. O envio ao GitHub continua pelo ./push.sh no terminal.</p>
    </div>

    <div class="card">
        <h2>Histórico de mudanças</h2>
        <?php if (!$history): ?>
            <p class="hint">Nenhuma mudança registrada ainda.</p>
        <?php else: ?>
            <table>
                <tr><th>Quando (Brasília)</th><th>Ajuste</th><th>De</th><th>Para</th><th>Onde</th></tr>
                <?php $fields = configFields(); foreach ($history as $hrow): ?>
                    <tr>
                        <td><?= h((new DateTimeImmutable($hrow['timestamp']))->setTimezone(new DateTimeZone('America/Sao_Paulo'))->format('d/m H:i')) ?></td>
                        <td><?= h($fields[$hrow['key']]['label'] ?? $hrow['key']) ?></td>
                        <td><?= h($hrow['old']) ?></td>
                        <td><?= h($hrow['new']) ?></td>
                        <td><?= h($hrow['source']) ?></td>
                    </tr>
                <?php endforeach; ?>
            </table>
        <?php endif; ?>
    </div>

    <div class="grid">
        <div class="card">
            <h2>Trocar senha</h2>
            <form method="post"><?= csrfField() ?><input type="hidden" name="action" value="change_password">
                <div class="row"><input type="password" name="current_password" placeholder="Senha atual" required style="width:100%"></div>
                <div class="row"><input type="password" name="new_password" placeholder="Nova senha (mín. 8)" required style="width:100%"></div>
                <div class="row"><input type="password" name="new_password2" placeholder="Repita a nova senha" required style="width:100%"></div>
                <div class="row"><button type="submit">Trocar senha</button></div>
            </form>
        </div>
        <div class="card">
            <h2>Sessão</h2>
            <form method="post"><?= csrfField() ?><input type="hidden" name="action" value="logout"><button type="submit">Sair</button></form>
            <p class="hint">A sessão expira após <?= SESSION_IDLE_SECONDS / 3600 ?>h sem uso. O painel live.php continua aberto pra visualizar; ações lá também exigem este login.</p>
        </div>
    </div>
<?php endif; ?>
</main>
</body>
</html>
