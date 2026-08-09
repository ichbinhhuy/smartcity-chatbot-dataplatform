from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    'owner': 'smartcity',
    'depends_on_past': False,
    'start_date': datetime(2026, 8, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'smartcity_lakehouse_pipeline',
    default_args=default_args,
    description='Automated Pipeline: Bronze Ingestion -> Silver Cleansing -> Gold Aggregation -> Data Quality Tests',
    schedule_interval='@daily',
    catchup=False
)

# Task 1: Ingest Raw Landing Data to Bronze
ingest_bronze = BashOperator(
    task_id='ingest_raw_to_bronze',
    bash_command='STARROCKS_HOST=http://starrocks:8030 MINIO_HOST=http://minio:9000 python /opt/airflow/mock_engine/ingest_bronze.py',
    dag=dag,
)

# Task 2: Run dbt Silver Transformation
transform_silver = BashOperator(
    task_id='dbt_run_silver',
    bash_command='dbt run --select path:models/silver --project-dir /opt/airflow/dags/../transform --profiles-dir /opt/airflow/dags/../transform',
    dag=dag,
)

# Task 3: Run dbt Gold Transformation
transform_gold = BashOperator(
    task_id='dbt_run_gold',
    bash_command='dbt run --select path:models/gold --project-dir /opt/airflow/dags/../transform --profiles-dir /opt/airflow/dags/../transform',
    dag=dag,
)

# Task 4: Execute dbt Data Quality Tests
data_quality_test = BashOperator(
    task_id='dbt_data_quality_test',
    bash_command='dbt test --project-dir /opt/airflow/dags/../transform --profiles-dir /opt/airflow/dags/../transform',
    dag=dag,
)

# Pipeline Dependencies: Ingest Bronze -> Silver -> Gold -> DQ Test
ingest_bronze >> transform_silver >> transform_gold >> data_quality_test
