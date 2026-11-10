\getenv reader_password SOC_JMETER_DB_PASSWORD

CREATE ROLE soc_jmeter_reader LOGIN PASSWORD :'reader_password';
CREATE SCHEMA jmeter_lab;
CREATE TABLE jmeter_lab.reports (
    id integer PRIMARY KEY,
    titulo text NOT NULL,
    severidad text NOT NULL
);

INSERT INTO jmeter_lab.reports (id, titulo, severidad)
SELECT id, 'Reporte sintético ' || id,
       (ARRAY['baja', 'media', 'alta', 'critica'])[1 + id % 4]
FROM generate_series(1, 1200) AS fixture(id);

GRANT USAGE ON SCHEMA jmeter_lab TO soc_jmeter_reader;
GRANT SELECT ON jmeter_lab.reports TO soc_jmeter_reader;
ANALYZE jmeter_lab.reports;
