import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('169.58.116.61', username='root', password='1601Jcs332503')

cmd = 'docker pull evoapicloud/evolution-api:latest'
_, out, err = ssh.exec_command(cmd)
print("PULL STATUS:")
print(out.read().decode('utf-8'))
print(err.read().decode('utf-8'))

ssh.close()
