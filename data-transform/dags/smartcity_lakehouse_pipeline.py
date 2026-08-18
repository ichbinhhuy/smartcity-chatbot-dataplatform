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
    description='Automated Enterprise Pipeline: NiFi Ingestion -> Silver Cleansing -> Silver DQ Gate -> Gold Aggregation -> Gold DQ Gate',
    schedule_interval='@daily',
    catchup=False
)

# Task 1: Trigger Apache NiFi 5-Stream Ingestion via NiFi REST API
ingest_bronze = BashOperator(
    task_id='trigger_nifi_ingestion',
    bash_command="""python -c "
import requests, time, sys

NIFI_API = 'http://nifi:8080/nifi-api'

try:
    # 1. Lay Root Process Group ID
    res = requests.get(f'{NIFI_API}/flow/process-groups/root', timeout=10)
    if res.status_code != 200:
        print(f'[NiFi Warning] Khong ket noi duoc NiFi API ({res.status_code}). Chay Ingestion truc tiep...')
        import subprocess
        subprocess.check_call(['python', '/opt/airflow/mock_engine/ingest_bronze.py'])
        sys.exit(0)

    root_id = res.json()['processGroupFlow']['id']
    print(f'[NiFi] Phat hien Root Process Group ID: {root_id}')

    # 2. Start toan bo 5 luong Processors tren NiFi
    start_payload = {'id': root_id, 'state': 'RUNNING'}
    res_start = requests.put(f'{NIFI_API}/flow/process-groups/{root_id}', json=start_payload, timeout=10)
    print(f'[NiFi] Kich hoat 5 luong Ingestion (Status: {res_start.status_code})...')

    # Cho NiFi hut du lieu
    time.sleep(10)

    # 3. Stop Processors de giai phong tai nguyen
    stop_payload = {'id': root_id, 'state': 'STOPPED'}
    requests.put(f'{NIFI_API}/flow/process-groups/{root_id}', json=stop_payload, timeout=10)
    print('[NiFi] Ingestion 5 luong hoan tat.')
except Exception as e:
    print(f'[NiFi Fallback] {e}. Chay Ingestion truc tiep qua Stream Load...')
    import subprocess
    subprocess.check_call(['python', '/opt/airflow/mock_engine/ingest_bronze.py'])
" """,
    dag=dag,
)

# Task 2: Run dbt Silver Transformation (Làm sạch & Khử trùng lặp)
transform_silver = BashOperator(
    task_id='dbt_run_silver',
    bash_command='dbt run --select path:models/silver --project-dir /opt/airflow/dags/../transform --profiles-dir /opt/airflow/dags/../transform',
    dag=dag,
)

# Task 3: Quality Gate 1 - Kiểm thử chất lượng tầng Silver (38 tests)
test_silver = BashOperator(
    task_id='dbt_test_silver_quality_gate',
    bash_command='dbt test --select path:models/silver --project-dir /opt/airflow/dags/../transform --profiles-dir /opt/airflow/dags/../transform',
    dag=dag,
)

# Task 4: Run dbt Gold Transformation (5 Fact + Dim + KPI Livability Mart)
transform_gold = BashOperator(
    task_id='dbt_run_gold',
    bash_command='dbt run --select path:models/gold --project-dir /opt/airflow/dags/../transform --profiles-dir /opt/airflow/dags/../transform',
    dag=dag,
)

# Task 5: Quality Gate 2 - Kiểm thử chất lượng tầng Gold (4 tests)
test_gold = BashOperator(
    task_id='dbt_test_gold_quality_gate',
    bash_command='dbt test --select path:models/gold --project-dir /opt/airflow/dags/../transform --profiles-dir /opt/airflow/dags/../transform',
    dag=dag,
)

# Pipeline Dependencies: Ingest Bronze -> Silver -> Test Silver -> Gold -> Test Gold
ingest_bronze >> transform_silver >> test_silver >> transform_gold >> test_gold
