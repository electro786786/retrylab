import os
import requests
import time

os.system('docker compose rm -s -f target_app')
os.system('env BUG_8_KEY_SAVED_BEFORE_WORK=True BUG_8_CRASH_AFTER_KEY_SAVE=1 docker compose up -d target_app')
time.sleep(2)
os.system('docker compose exec target_app env | grep BUG_8')

for _ in range(30):
    try:
        if requests.get('http://localhost:8000/docs').status_code == 200:
            break
    except:
        pass
    time.sleep(1)

key = 'test-bug8-' + str(time.time())
cust = requests.post('http://localhost:8000/customers', headers={'Idempotency-Key': 'setup-' + key}, json={'name': 'test', 'email': 'test@example.com'}).json()
cid = cust['id']

r = requests.post('http://localhost:8000/payments', headers={'Idempotency-Key': key}, json={'customer_id': cid, 'amount': 1000})
print('Attempt 1 response:', r.status_code, r.text)
