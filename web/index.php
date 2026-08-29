<?php
declare(strict_types=1);

/**
 * CRYPTO RADAR V3
 * Dashboard Web
 *
 * Compatível com PHP sem mbstring.
 */

const BASE_DIR = __DIR__ . '/..';
const DB_FILE  = BASE_DIR . '/data/crypto_radar.db';

function h(mixed $value): string
{
    return htmlspecialchars(
        (string) $value,
        ENT_QUOTES | ENT_SUBSTITUTE,
        'UTF-8'
    );
}

function numberValue(mixed $value, int $decimals = 2): string
{
    if ($value === null || $value === '') {
        return '-';
    }

    if (!is_numeric($value)) {
        return h($value);
    }

    return number_format(
        (float) $value,
        $decimals,
        ',',
        '.'
    );
}

function percentValue(mixed $value): string
{
    if ($value === null || $value === '') {
        return '-';
    }

    if (!is_numeric($value)) {
        return h($value);
    }

    $value = (float) $value;

    return ($value >= 0 ? '+' : '') .
        number_format($value, 2, ',', '.') . '%';
}

function db(): PDO
{
    if (!file_exists(DB_FILE)) {
        throw new RuntimeException(
            'Banco de dados não encontrado: ' . DB_FILE
        );
    }

    return new PDO(
        'sqlite:' . DB_FILE,
        null,
        null,
        [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]
    );
}

function tableExists(PDO $pdo, string $table): bool
{
    $stmt = $pdo->prepare(
        "SELECT name
         FROM sqlite_master
         WHERE type = 'table'
         AND name = :table
         LIMIT 1"
    );

    $stmt->execute(['table' => $table]);

    return $stmt->fetch() !== false;
}

function getColumns(PDO $pdo, string $table): array
{
    if (!tableExists($pdo, $table)) {
        return [];
    }

    $safeTable = str_replace('"', '""', $table);

    $rows = $pdo->query(
        'PRAGMA table_info("' . $safeTable . '")'
    )->fetchAll();

    $columns = [];

    foreach ($rows as $row) {
        if (isset($row['name'])) {
            $columns[] = $row['name'];
        }
    }

    return $columns;
}

function firstExistingColumn(
    array $columns,
    array $candidates
): ?string {
    foreach ($candidates as $candidate) {
        if (in_array($candidate, $columns, true)) {
            return $candidate;
        }
    }

    return null;
}

function safeIdentifier(?string $identifier): string
{
    if (
        $identifier === null ||
        !preg_match(
            '/^[A-Za-z_][A-Za-z0-9_]*$/',
            $identifier
        )
    ) {
        throw new InvalidArgumentException(
            'Identificador SQL inválido.'
        );
    }

    return '"' . $identifier . '"';
}

function renderSparkline(array $prices): string
{
    $count = count($prices);

    if ($count < 2) {
        return '';
    }

    $width = 180;
    $height = 40;
    $padding = 4;

    $min = min($prices);
    $max = max($prices);
    $range = $max - $min;

    // Série flat (sem variação) - desenha uma linha reta no meio em vez
    // de dividir por zero.
    if ($range <= 0.0) {
        $range = 1.0;
    }

    $stepX = ($width - $padding * 2) / ($count - 1);

    $points = [];
    foreach ($prices as $index => $price) {
        $x = $padding + $index * $stepX;
        $normalized = ($price - $min) / $range;
        $y = $height - $padding - ($normalized * ($height - $padding * 2));
        $points[] = sprintf('%.2f,%.2f', $x, $y);
    }

    $trendUp = end($prices) >= reset($prices);

    // Reaproveita as mesmas cores de positive/negative já usadas no
    // resto do dashboard - não introduz paleta nova.
    $stroke = $trendUp ? '#65dfa0' : '#ff778b';

    $lastPoint = explode(',', $points[$count - 1]);

    return sprintf(
        '<svg viewBox="0 0 %d %d" width="%d" height="%d" class="sparkline" role="img" aria-label="tendência de preço">'
        . '<polyline points="%s" fill="none" stroke="%s" stroke-width="2" '
        . 'stroke-linecap="round" stroke-linejoin="round" />'
        . '<circle cx="%s" cy="%s" r="2.5" fill="%s" />'
        . '</svg>',
        $width,
        $height,
        $width,
        $height,
        h(implode(' ', $points)),
        $stroke,
        h($lastPoint[0]),
        h($lastPoint[1]),
        $stroke
    );
}

function classificationUpper(string $value): string
{
    /*
     * Não usa mbstring.
     *
     * As classificações do Crypto Radar são normalmente ASCII:
     * FORTE, NEUTRO, FRACO, etc.
     *
     * Para manter compatibilidade, apenas convertemos caracteres
     * ASCII para maiúsculas.
     */
    return strtoupper(trim($value));
}

$error = null;

$rows = [];

$stats = [
    'total'   => 0,
    'symbols' => 0,
    'strong'  => 0,
    'neutral' => 0,
    'weak'    => 0,
];

try {
    $pdo = db();

    $table = 'scanner_v3_results';

    if (!tableExists($pdo, $table)) {
        throw new RuntimeException(
            "A tabela {$table} não existe no banco."
        );
    }

    $columns = getColumns($pdo, $table);

    /*
     * Descoberta automática das colunas.
     */

    $symbolColumn = firstExistingColumn(
        $columns,
        [
            'symbol',
            'market',
            'pair',
            'ticker',
        ]
    );

    $priceColumn = firstExistingColumn(
        $columns,
        [
            'price',
            'close',
            'current_price',
        ]
    );

    $scoreColumn = firstExistingColumn(
        $columns,
        [
            'score',
            'total_score',
        ]
    );

    $rsiColumn = firstExistingColumn(
        $columns,
        [
            'rsi',
        ]
    );

    $momentumColumn = firstExistingColumn(
        $columns,
        [
            'momentum_4h',
            'momentum',
        ]
    );

    $volumeColumn = firstExistingColumn(
        $columns,
        [
            'relative_volume',
            'volume_relative',
        ]
    );

    $confidenceColumn = firstExistingColumn(
        $columns,
        [
            'confidence',
        ]
    );

    $classificationColumn = firstExistingColumn(
        $columns,
        [
            'classification',
            'class',
            'signal',
        ]
    );

    $signalColumn = firstExistingColumn(
        $columns,
        [
            'signal',
        ]
    );

    $runAtColumn = firstExistingColumn(
        $columns,
        [
            'run_at',
        ]
    );

    $timestampColumn = firstExistingColumn(
        $columns,
        [
            'timestamp',
            'created_at',
            'analysis_time',
            'datetime',
            'observed_at',
        ]
    );

    /*
     * Total de análises.
     */

    $stats['total'] = (int) $pdo
        ->query(
            'SELECT COUNT(*) FROM "' . $table . '"'
        )
        ->fetchColumn();

    /*
     * Símbolos únicos.
     */

    if ($symbolColumn !== null) {
        $symbolSql = safeIdentifier($symbolColumn);

        $stats['symbols'] = (int) $pdo
            ->query(
                "SELECT COUNT(DISTINCT {$symbolSql})
                 FROM \"{$table}\""
            )
            ->fetchColumn();
    }

    /*
     * SELECT dinâmico.
     */

    $select = [];

    if ($symbolColumn !== null) {
        $select[] =
            safeIdentifier($symbolColumn) .
            ' AS symbol';
    } else {
        $select[] = "'' AS symbol";
    }

    if ($priceColumn !== null) {
        $select[] =
            safeIdentifier($priceColumn) .
            ' AS price';
    } else {
        $select[] = 'NULL AS price';
    }

    if ($scoreColumn !== null) {
        $select[] =
            safeIdentifier($scoreColumn) .
            ' AS score';
    } else {
        $select[] = 'NULL AS score';
    }

    if ($rsiColumn !== null) {
        $select[] =
            safeIdentifier($rsiColumn) .
            ' AS rsi';
    } else {
        $select[] = 'NULL AS rsi';
    }

    if ($momentumColumn !== null) {
        $select[] =
            safeIdentifier($momentumColumn) .
            ' AS momentum';
    } else {
        $select[] = 'NULL AS momentum';
    }

    if ($volumeColumn !== null) {
        $select[] =
            safeIdentifier($volumeColumn) .
            ' AS relative_volume';
    } else {
        $select[] = 'NULL AS relative_volume';
    }

    if ($confidenceColumn !== null) {
        $select[] =
            safeIdentifier($confidenceColumn) .
            ' AS confidence';
    } else {
        $select[] = 'NULL AS confidence';
    }

    if ($classificationColumn !== null) {
        $select[] =
            safeIdentifier($classificationColumn) .
            ' AS classification';
    } else {
        $select[] = "'' AS classification";
    }

    if ($signalColumn !== null) {
        $select[] =
            safeIdentifier($signalColumn) .
            ' AS signal_raw';
    } else {
        $select[] = "'' AS signal_raw";
    }

    if ($timestampColumn !== null) {
        $select[] =
            safeIdentifier($timestampColumn) .
            ' AS analysis_time';
    } else {
        $select[] = 'NULL AS analysis_time';
    }

    /*
     * Ordenação.
     */

    if ($timestampColumn !== null) {
        $orderBy =
            safeIdentifier($timestampColumn) . ' DESC';
    } else {
        $orderBy = 'rowid DESC';
    }

    $sql = sprintf(
        'SELECT %s FROM "%s" ORDER BY %s LIMIT 100',
        implode(', ', $select),
        $table,
        $orderBy
    );

    $rows = $pdo->query($sql)->fetchAll();

    /*
     * Melhores oportunidades de compra (rodada mais recente do
     * scanner). Só é possível separar "a rodada mais recente" de
     * "rodadas anteriores que caíram no mesmo candle" quando a coluna
     * run_at existe (execuções mais antigas do banco não têm essa
     * coluna e caem no fallback por "timestamp").
     */

    $topPicks = [];

    if ($signalColumn !== null) {
        $roundColumn = $runAtColumn ?? $timestampColumn;

        if ($roundColumn !== null) {
            $roundSql = safeIdentifier($roundColumn);
            $signalSql = safeIdentifier($signalColumn);

            $latestRound = $pdo
                ->query("SELECT MAX({$roundSql}) FROM \"{$table}\"")
                ->fetchColumn();

            if ($latestRound !== false && $latestRound !== null) {
                $topSql = implode(', ', $select) . ", {$roundSql} AS round_key";

                $stmt = $pdo->prepare(
                    "SELECT {$topSql}
                     FROM \"{$table}\"
                     WHERE {$roundSql} = :round
                       AND {$signalSql} IN ('COMPRA', 'COMPRA FORTE')
                     ORDER BY "
                    . ($scoreColumn !== null ? safeIdentifier($scoreColumn) . ' DESC' : 'rowid DESC')
                    . " LIMIT 10"
                );
                $stmt->execute(['round' => $latestRound]);
                $topPicks = $stmt->fetchAll();
            }
        }
    }

    /*
     * Histórico recente de preço por símbolo (pra desenhar o
     * sparkline de cada card de destaque). Uma consulta por símbolo -
     * o número de picks é pequeno (até 10), então isso não pesa.
     */

    $priceHistory = [];

    if ($topPicks && $symbolColumn !== null && $priceColumn !== null) {
        $orderColumn = $runAtColumn ?? $timestampColumn;
        $historySql = $orderColumn !== null
            ? safeIdentifier($orderColumn) . ' DESC'
            : 'rowid DESC';

        $stmt = $pdo->prepare(
            'SELECT ' . safeIdentifier($priceColumn) . ' AS price
             FROM "' . $table . '"
             WHERE ' . safeIdentifier($symbolColumn) . ' = :symbol
             ORDER BY ' . $historySql . '
             LIMIT 30'
        );

        foreach ($topPicks as $pick) {
            $sym = (string) $pick['symbol'];

            if (isset($priceHistory[$sym])) {
                continue;
            }

            $stmt->execute(['symbol' => $sym]);
            $values = array_map(
                static fn($row) => (float) $row['price'],
                $stmt->fetchAll()
            );

            // Vem em ordem DESC (mais recente primeiro) - inverte pra
            // ordem cronológica antes de desenhar.
            $priceHistory[$sym] = array_reverse($values);
        }
    }

    /*
     * Classificação dos sinais.
     */

    foreach ($rows as $row) {
        $classification = classificationUpper(
            (string) ($row['classification'] ?? '')
        );

        if (
            str_contains(
                $classification,
                'MUITO FORTE'
            ) ||
            $classification === 'FORTE'
        ) {
            $stats['strong']++;
        } elseif (
            str_contains(
                $classification,
                'NEUTRO'
            ) ||
            str_contains(
                $classification,
                'NEUTRA'
            )
        ) {
            $stats['neutral']++;
        } elseif (
            str_contains(
                $classification,
                'FRACO'
            ) ||
            str_contains(
                $classification,
                'VENDA'
            )
        ) {
            $stats['weak']++;
        }
    }

} catch (Throwable $e) {
    $error = $e->getMessage();
}

?>
<!DOCTYPE html>
<html lang="pt-BR">

<head>

    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <meta
        http-equiv="refresh"
        content="60"
    >

    <title>Crypto Radar V3</title>

    <style>

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            font-family:
                Inter,
                system-ui,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;

            background: #0b1020;
            color: #e8edf7;
        }

        header {
            border-bottom:
                1px solid #202a43;

            background: #0e1528;

            padding: 22px 30px;
        }

        .header-inner {
            max-width: 1400px;

            margin: auto;

            display: flex;

            align-items: center;

            justify-content: space-between;

            gap: 20px;
        }

        .brand h1 {
            margin: 0;

            font-size: 25px;

            letter-spacing: .4px;
        }

        .brand p {
            margin: 6px 0 0;

            color: #8995ad;

            font-size: 13px;
        }

        .status {
            display: flex;

            align-items: center;

            gap: 8px;

            color: #69e29b;

            font-size: 13px;
        }

        .dot {
            width: 9px;
            height: 9px;

            border-radius: 50%;

            background: #69e29b;
        }

        main {
            max-width: 1400px;

            margin: 0 auto;

            padding: 30px;
        }

        .error {
            background: #321820;

            border:
                1px solid #713044;

            color: #ffb8c6;

            padding: 18px;

            border-radius: 12px;

            margin-bottom: 25px;
        }

        .cards {
            display: grid;

            grid-template-columns:
                repeat(4, minmax(0, 1fr));

            gap: 16px;

            margin-bottom: 28px;
        }

        .card {
            background: #111a2e;

            border:
                1px solid #202b45;

            border-radius: 14px;

            padding: 20px;
        }

        .card-label {
            color: #8995ad;

            font-size: 12px;

            text-transform: uppercase;

            letter-spacing: .8px;
        }

        .card-value {
            margin-top: 8px;

            font-size: 28px;

            font-weight: 700;
        }

        .section {
            background: #111a2e;

            border:
                1px solid #202b45;

            border-radius: 14px;

            overflow: hidden;
        }

        .section-header {
            padding: 20px;

            border-bottom:
                1px solid #202b45;
        }

        .section-header h2 {
            margin: 0;

            font-size: 18px;
        }

        .section-header p {
            margin: 6px 0 0;

            color: #8995ad;

            font-size: 13px;
        }

        .table-wrapper {
            overflow-x: auto;
        }

        table {
            width: 100%;

            border-collapse: collapse;

            min-width: 950px;
        }

        th {
            background: #0d1527;

            color: #8995ad;

            font-size: 11px;

            text-transform: uppercase;

            letter-spacing: .7px;

            text-align: left;

            padding: 13px 15px;
        }

        td {
            border-top:
                1px solid #1d2740;

            padding: 14px 15px;

            font-size: 13px;
        }

        tr:hover td {
            background: #141f36;
        }

        .symbol {
            font-weight: 700;

            color: #ffffff;
        }

        .score {
            font-weight: 700;
        }

        .positive {
            color: #65dfa0;
        }

        .negative {
            color: #ff778b;
        }

        .neutral {
            color: #f2c96d;
        }

        .badge {
            display: inline-block;

            border-radius: 999px;

            padding: 5px 10px;

            font-size: 11px;

            font-weight: 700;

            background: #1c2941;
        }

        .badge.buy {
            background: #103d27;
            color: #6bf0a4;
            border: 1px solid #1f7a4d;
        }

        .badge.buy-strong {
            background: #123a1f;
            color: #7dffb0;
            border: 1px solid #2fae66;
            box-shadow: 0 0 0 1px rgba(45, 220, 120, .25);
        }

        .picks-grid {
            display: grid;

            grid-template-columns:
                repeat(auto-fill, minmax(220px, 1fr));

            gap: 14px;

            margin-bottom: 28px;
        }

        .pick-card {
            background:
                linear-gradient(
                    155deg,
                    #0f2a1c,
                    #111a2e
                );

            border: 1px solid #1f7a4d;

            border-radius: 14px;

            padding: 18px;
        }

        .pick-card .pick-symbol {
            font-size: 17px;
            font-weight: 700;
            color: #ffffff;
        }

        .pick-card .pick-signal {
            margin-top: 6px;
        }

        .pick-card .pick-meta {
            margin-top: 10px;
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: #9db3a6;
        }

        .pick-card .pick-meta strong {
            color: #e8edf7;
            font-size: 14px;
        }

        .pick-sparkline {
            margin-top: 10px;
            line-height: 0;
        }

        .pick-sparkline svg {
            width: 100%;
            height: 36px;
            display: block;
        }

        tr.row-buy td {
            background: rgba(45, 220, 120, .06);
            border-left: 3px solid #2fae66;
        }

        tr.row-buy:hover td {
            background: rgba(45, 220, 120, .12);
        }

        footer {
            max-width: 1400px;

            margin: 0 auto;

            padding:
                25px 30px 40px;

            color: #66738d;

            font-size: 12px;
        }

        @media (max-width: 900px) {

            .cards {
                grid-template-columns:
                    repeat(2, minmax(0, 1fr));
            }

            main {
                padding: 20px;
            }

            header {
                padding: 18px 20px;
            }

            .header-inner {
                align-items: flex-start;

                flex-direction: column;
            }
        }

        @media (max-width: 550px) {

            .cards {
                grid-template-columns: 1fr;
            }

        }

    </style>

</head>

<body>

<header>

    <div class="header-inner">

        <div class="brand">

            <h1>
                CRYPTO RADAR V3
            </h1>

            <p>
                Scanner • análise técnica • descoberta de oportunidades
            </p>

        </div>

        <div class="status">

            <span class="dot"></span>

            Sistema online

        </div>

    </div>

</header>

<main>

<?php if ($error !== null): ?>

    <div class="error">

        <strong>
            Erro ao carregar o Crypto Radar
        </strong>

        <br><br>

        <?= h($error) ?>

    </div>

<?php else: ?>

    <section class="cards">

        <div class="card">

            <div class="card-label">
                Análises
            </div>

            <div class="card-value">
                <?= number_format(
                    $stats['total'],
                    0,
                    ',',
                    '.'
                ) ?>
            </div>

        </div>

        <div class="card">

            <div class="card-label">
                Símbolos
            </div>

            <div class="card-value">
                <?= number_format(
                    $stats['symbols'],
                    0,
                    ',',
                    '.'
                ) ?>
            </div>

        </div>

        <div class="card">

            <div class="card-label">
                Sinais fortes
            </div>

            <div class="card-value positive">
                <?= number_format(
                    $stats['strong'],
                    0,
                    ',',
                    '.'
                ) ?>
            </div>

        </div>

        <div class="card">

            <div class="card-label">
                Neutros
            </div>

            <div class="card-value neutral">
                <?= number_format(
                    $stats['neutral'],
                    0,
                    ',',
                    '.'
                ) ?>
            </div>

        </div>

    </section>

    <?php if ($topPicks): ?>

    <section>

        <div class="section-header" style="padding: 0 0 14px;">

            <h2>
                🎯 Melhores oportunidades de compra agora
            </h2>

            <p>
                Sinal COMPRA/COMPRA FORTE na rodada mais recente do scanner,
                ordenado por score. Isto reflete o que o radar está
                classificando como forte agora - não é recomendação validada
                (ver histórico de backtest do projeto).
            </p>

        </div>

        <div class="picks-grid">

            <?php foreach ($topPicks as $pick): ?>

                <?php
                $pickSignal = trim((string) ($pick['signal_raw'] ?? ''));
                $isStrong = str_contains(classificationUpper($pickSignal), 'FORTE');
                ?>

                <div class="pick-card">

                    <div class="pick-symbol">
                        <?= h($pick['symbol']) ?>
                    </div>

                    <div class="pick-signal">
                        <span class="badge <?= $isStrong ? 'buy-strong' : 'buy' ?>">
                            <?= h($pickSignal !== '' ? $pickSignal : 'COMPRA') ?>
                        </span>
                    </div>

                    <div class="pick-meta">
                        <span>Score <strong><?= numberValue($pick['score'], 0) ?></strong></span>
                        <span>Confiança <strong><?= numberValue($pick['confidence'], 0) ?>%</strong></span>
                    </div>

                    <div class="pick-meta">
                        <span>Preço <strong><?= numberValue($pick['price'], 8) ?></strong></span>
                    </div>

                    <?php
                    $sparklinePrices = $priceHistory[(string) $pick['symbol']] ?? [];
                    $sparklineSvg = renderSparkline($sparklinePrices);
                    ?>

                    <?php if ($sparklineSvg !== ''): ?>

                        <div class="pick-sparkline">
                            <?= $sparklineSvg ?>
                        </div>

                    <?php endif; ?>

                </div>

            <?php endforeach; ?>

        </div>

    </section>

    <?php endif; ?>

    <section class="section">

        <div class="section-header">

            <h2>
                Últimas análises
            </h2>

            <p>
                Dados recentes da tabela
                <strong>
                    scanner_v3_results
                </strong>
            </p>

        </div>

        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>

                        <th>
                            Mercado
                        </th>

                        <th>
                            Preço
                        </th>

                        <th>
                            Score
                        </th>

                        <th>
                            RSI
                        </th>

                        <th>
                            Momentum 4H
                        </th>

                        <th>
                            Volume Rel.
                        </th>

                        <th>
                            Confiança
                        </th>

                        <th>
                            Classificação
                        </th>

                        <th>
                            Sinal
                        </th>

                        <th>
                            Data
                        </th>

                    </tr>

                </thead>

                <tbody>

                <?php if (!$rows): ?>

                    <tr>

                        <td colspan="10">

                            Nenhuma análise encontrada.

                        </td>

                    </tr>

                <?php else: ?>

                    <?php foreach ($rows as $row): ?>

                        <?php

                        $momentum =
                            $row['momentum'];

                        $momentumClass = '';

                        if (
                            is_numeric($momentum)
                        ) {
                            $momentumClass =
                                (float) $momentum >= 0
                                    ? 'positive'
                                    : 'negative';
                        }

                        $classification =
                            trim(
                                (string)
                                (
                                    $row['classification']
                                    ?? ''
                                )
                            );

                        $classificationUpper =
                            classificationUpper(
                                $classification
                            );

                        $badgeClass = 'neutral';

                        if (
                            str_contains(
                                $classificationUpper,
                                'FORTE'
                            )
                        ) {
                            $badgeClass =
                                'positive';

                        } elseif (
                            str_contains(
                                $classificationUpper,
                                'FRACO'
                            ) ||
                            str_contains(
                                $classificationUpper,
                                'VENDA'
                            )
                        ) {
                            $badgeClass =
                                'negative';
                        }

                        $date =
                            $row['analysis_time']
                            ?? null;

                        $signalRaw =
                            trim(
                                (string)
                                (
                                    $row['signal_raw']
                                    ?? ''
                                )
                            );

                        $signalUpper = classificationUpper($signalRaw);

                        $isBuySignal =
                            str_contains($signalUpper, 'COMPRA');

                        $isStrongBuy =
                            $isBuySignal &&
                            str_contains($signalUpper, 'FORTE');

                        ?>

                        <tr<?= $isBuySignal ? ' class="row-buy"' : '' ?>>

                            <td class="symbol">

                                <?= h(
                                    $row['symbol']
                                ) ?>

                            </td>

                            <td>

                                <?= numberValue(
                                    $row['price'],
                                    8
                                ) ?>

                            </td>

                            <td class="score">

                                <?= numberValue(
                                    $row['score'],
                                    0
                                ) ?>

                            </td>

                            <td>

                                <?= numberValue(
                                    $row['rsi'],
                                    2
                                ) ?>

                            </td>

                            <td
                                class="<?= h(
                                    $momentumClass
                                ) ?>"
                            >

                                <?= percentValue(
                                    $momentum
                                ) ?>

                            </td>

                            <td>

                                <?= numberValue(
                                    $row['relative_volume'],
                                    2
                                ) ?>x

                            </td>

                            <td>

                                <?= numberValue(
                                    $row['confidence'],
                                    2
                                ) ?>

                            </td>

                            <td>

                                <span
                                    class="badge <?= h(
                                        $badgeClass
                                    ) ?>"
                                >

                                    <?= h(
                                        $classification !== ''
                                            ? $classification
                                            : 'N/D'
                                    ) ?>

                                </span>

                            </td>

                            <td>

                                <?php if ($isBuySignal): ?>

                                    <span class="badge <?= $isStrongBuy ? 'buy-strong' : 'buy' ?>">
                                        <?= h($signalRaw) ?>
                                    </span>

                                <?php else: ?>

                                    <?= h($signalRaw !== '' ? $signalRaw : '-') ?>

                                <?php endif; ?>

                            </td>

                            <td>

                                <?= h(
                                    $date !== null
                                        ? $date
                                        : '-'
                                ) ?>

                            </td>

                        </tr>

                    <?php endforeach; ?>

                <?php endif; ?>

                </tbody>

            </table>

        </div>

    </section>

<?php endif; ?>

</main>

<footer>

    Crypto Radar V3 • Banco: crypto_radar.db

</footer>

</body>

</html>


