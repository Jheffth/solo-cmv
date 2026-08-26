import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

# 1. Cria schema evolution se não existir
cmd1 = 'docker exec solo_cmv_db psql -U solo_cmv -d solo_cmv -c "CREATE SCHEMA IF NOT EXISTS evolution;"'
_, out1, err1 = ssh.exec_command(cmd1)
print("SCHEMA RESULT:", out1.read().decode('utf-8'), err1.read().decode('utf-8'))

# 2. Confere senha no .env do servidor
cmd2 = 'grep DATABASE_URL /var/www/solo-cmv/.env'
_, out2, _ = ssh.exec_command(cmd2)
print("DATABASE_URL NO .ENV:", out2.read().decode('utf-8'))

ssh.close()
