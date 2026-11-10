## Diagnóstico

Falla de conectividad u operatividad en servicio DNS: la IP 143.88.255.10 envía ráfagas continuas de consultas DNS al resolver 10.0.10.1 a intervalos regulares (~30 s) sin recibir respuesta (estado Zeek S0), mientras que otros clientes (como 143.88.1.51) resuelven correctamente contra 143.88.1.1.

## Evaluación del auditor

El patrón observado (264 conexiones UDP/53 en estado S0 hacia 10.0.10.1 con reintentos periódicos) corresponde a retransmisiones automáticas provocadas por un servidor DNS inaccesible o una configuración errónea en el cliente 143.88.255.10, sin elementos concluyentes de actividad maliciosa ni exfiltración.

## Comandos de mitigación propuestos

- ping -c 4 10.0.10.1
- dig @10.0.10.1 localhost
- cat /etc/resolv.conf
- tcpdump -nn -i any host 143.88.255.10 and port 53