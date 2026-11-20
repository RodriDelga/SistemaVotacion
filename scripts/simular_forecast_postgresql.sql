-- Simulación en public. Ejecute esto en la rama principal que use para pruebas.
-- Ejecute el bloque DO en modo autocommit. Después ejecute la consulta final.
DO $$
DECLARE
    -- Configure una de estas dos variables únicamente si falta el evento de un voto previo.
    fecha_real_del_voto_previo CONSTANT timestamptz := NULL;
    voto_previo_es_de_prueba CONSTANT boolean := false;
    total_votantes_que_votaron bigint;
    total_votos_con_fecha bigint;
    personas_demo bigint;
    votantes_demo bigint;
    eventos_demo bigint;
BEGIN
    LOCK TABLE public.voter, public.ballot, public.dashboardevent IN SHARE ROW EXCLUSIVE MODE;

    SELECT count(*) FILTER (WHERE "hasVoted"),
           count(*) FILTER (WHERE "cardUid" ~ '^DEMO_FORECAST_[0-9]+$'),
           count(*) FILTER (WHERE "hasVoted" AND "cardUid" ~ '^DEMO_FORECAST_[0-9]+$')
    INTO total_votantes_que_votaron, personas_demo, votantes_demo
    FROM public.voter;

    SELECT count(*), count(*) FILTER (WHERE device = 'DEMO FORECAST')
    INTO total_votos_con_fecha, eventos_demo
    FROM public.dashboardevent
    WHERE kind = 'vote' AND status = 'ok';

    IF total_votantes_que_votaron <> total_votos_con_fecha THEN
        IF total_votantes_que_votaron = 1 AND total_votos_con_fecha = 0
           AND (fecha_real_del_voto_previo IS NOT NULL OR voto_previo_es_de_prueba) THEN
            IF fecha_real_del_voto_previo > statement_timestamp() THEN
                RAISE EXCEPTION 'La fecha del voto previo debe ser anterior a la carga.';
            END IF;
            INSERT INTO public.dashboardevent ("createdAt", kind, device, status)
            VALUES (
                coalesce(fecha_real_del_voto_previo, statement_timestamp() - INTERVAL '24 hours') AT TIME ZONE 'UTC',
                'vote',
                CASE WHEN fecha_real_del_voto_previo IS NULL THEN 'DEMO VOTO PREVIO SIN FECHA'
                     ELSE 'VOTO PREVIO RECUPERADO' END,
                'ok'
            );
        ELSE
            RAISE EXCEPTION 'La bitácora tiene % votos con fecha y el padrón tiene % votantes que ya votaron.',
                total_votos_con_fecha, total_votantes_que_votaron
                USING HINT = 'Para el caso de un solo voto previo sin evento, indica su fecha real. Si el voto era ficticio, puedes activar voto_previo_es_de_prueba.';
        END IF;
    END IF;

    IF personas_demo = 2000 AND votantes_demo = 1000 AND eventos_demo = 1000 THEN
        RAISE NOTICE 'La simulación ya existe. Ejecuta la consulta final para ver su horario.';
        RETURN;
    END IF;
    IF personas_demo > 0 OR eventos_demo > 0 THEN
        RAISE EXCEPTION 'El esquema public contiene registros parciales de una simulación previa.';
    END IF;

    CREATE TEMP TABLE simulacion_candidatos ON COMMIT DROP AS
    SELECT office, array_agg(id ORDER BY id) AS ids
    FROM public.candidate
    WHERE office = 'PRESIDENT'
       OR (office = 'GOVERNOR' AND upper(trim("stateName")) = 'JALISCO')
       OR (office = 'MAYOR' AND upper(trim("stateName")) = 'JALISCO'
                            AND upper(trim("municipalityName")) = 'GUADALAJARA')
    GROUP BY office;

    IF (SELECT count(*) FROM simulacion_candidatos) <> 3 THEN
        RAISE EXCEPTION 'Faltan candidatos para Presidencia, Gubernatura de Jalisco o Alcaldía de Guadalajara.'
            USING HINT = 'Verifica los campos office, stateName y municipalityName en la tabla candidate.';
    END IF;
    -- Padrón ficticio, con lectores deshabilitados para estas identidades de prueba.
    WITH slots AS (
        SELECT greatest(coalesce(max("fingerprintSlot"), 0), 0) AS last_slot FROM public.voter
    )
    INSERT INTO public.voter ("fullName", "cardUid", "fingerprintSlot", "faceEmbedding",
                       "stateName", "municipalityName", "hasVoted", "isEnabled")
    SELECT 'Persona de prueba ' || i, 'DEMO_FORECAST_' || i, last_slot + i, '',
           'JALISCO', 'GUADALAJARA', i <= 1000, false
    FROM generate_series(1, 2000) AS sequence(i)
    CROSS JOIN slots;

    -- Cada elector simulado emite una selección independiente para cada cargo.
    INSERT INTO public.ballot ("candidateId")
    SELECT pool.ids[1 + floor(random() * cardinality(pool.ids))::integer]
    FROM simulacion_candidatos AS pool
    CROSS JOIN generate_series(1, 1000);

    -- Jornada de 12 horas. La simulación llega a la hora 8 y sitúa el pico en la hora 6.
    -- Muestreo estratificado de una logística entre la apertura y el corte.
    WITH cutoff AS (
        SELECT date_trunc('minute', statement_timestamp()) AS sampled_at
    ), samples AS (
        SELECT sampled_at, i, (i - 1 + random()) / 1000 AS fraction
        FROM cutoff CROSS JOIN generate_series(1, 1000) AS sequence(i)
    ), logistic AS (
        SELECT sampled_at, i,
               1 / (1 + exp(4.8::double precision))
               + fraction * (1 / (1 + exp(-1.6::double precision)) - 1 / (1 + exp(4.8::double precision))) AS probability
        FROM samples
    )
    INSERT INTO public.dashboardevent ("createdAt", kind, device, status)
    SELECT (CASE WHEN i = 1000 THEN sampled_at
                ELSE sampled_at - INTERVAL '8 hours'
                     + INTERVAL '1 hour' * (6 + ln(probability / (1 - probability)) / 0.8)
           END) AT TIME ZONE 'UTC',
           'vote', 'DEMO FORECAST', 'ok'
    FROM logistic;
END;
$$;

-- Copie las dos cadenas resultantes al .env de la Pi.
SET TIME ZONE 'America/Mexico_City';
WITH simulation AS (
    SELECT (max("createdAt") AT TIME ZONE 'UTC') AS cutoff,
           count(*) AS eventos
    FROM public.dashboardevent
    WHERE kind = 'vote' AND status = 'ok' AND device = 'DEMO FORECAST'
)
SELECT 'DASHBOARD_ELECTION_OPENS_AT=' ||
           to_char(cutoff - INTERVAL '8 hours', 'YYYY-MM-DD"T"HH24:MI:SSTZH:TZM') AS apertura,
       'DASHBOARD_ELECTION_CLOSES_AT=' ||
           to_char(cutoff + INTERVAL '4 hours', 'YYYY-MM-DD"T"HH24:MI:SSTZH:TZM') AS cierre,
       eventos AS votos_simulados_con_fecha,
       (SELECT count(*) FROM public.dashboardevent WHERE kind = 'vote' AND status = 'ok') AS votos_con_fecha_totales,
       (SELECT count(*) FROM public.voter WHERE "hasVoted") AS votantes_que_votaron,
       (SELECT count(*) FROM public.ballot) AS selecciones_totales
FROM simulation;
