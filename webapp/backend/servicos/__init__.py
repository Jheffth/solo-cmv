"""
Serviços — regras de negócio independentes do canal de entrada.

O que está aqui não sabe se a chamada veio da tela web, de um bot do
Telegram ou de uma integração externa. Cada canal traduz a entrada, chama o
serviço e trata o erro do seu jeito. Isso evita que a mesma regra seja
reimplementada (e divirja) em cada lugar.
"""
