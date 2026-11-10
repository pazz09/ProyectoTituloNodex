## Diagnóstico

Falla operativa de conectividad DNS: el host 143.88.255.10 genera ráfagas periódicas repetitivas de solicitudes DNS UDP/53 dirigidas a la IP privada 10.0.10.1 sin recibir respuesta alguna (estado Zeek S0). No hay evidencia suficiente de tráfico malicioso o tunelización confirmada.

## Evaluación del auditor

Se observa un patrón anómalo de tráfico de red en el que 143.88.255.10 envía de forma continua cada 30 segundos múltiples consultas DNS hacia 10.0.10.1 con resultado S0 (sin respuesta/timeout). En contraste, otros clientes de la red (p. ej. 143.88.1.51) resuelven correctamente consultas contra 143.88.1.1 (estado SF). El comportamiento se alinea con una mala configuración de resolución DNS o la caída/inalcanzabilidad del servidor DNS interno 10.0.10.1, sin que se confirme tunelización o compromiso de seguridad.

## Comandos de mitigación propuestos

- cat /etc/resolv.conf
- resolvectl status
- dig @10.0.10.1 healthcheck.internal
- nc -zvu 10.0.10.1 53
- tcpdump -nn -i any host 143.88.255.10 and port 53