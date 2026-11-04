-- cBioHub's default destinations are a staging and a production portal. In this stack there is
-- one portal: the cbioportal service, imported into by the import_studies__local DAG.
DELETE FROM destinations;
INSERT INTO destinations (key, label, description, airflow_dag_id, sort_order) VALUES
    ('local', 'This portal', 'The cBioPortal running in this Docker Compose stack (http://localhost:8080).', 'import_studies__local', 1);
