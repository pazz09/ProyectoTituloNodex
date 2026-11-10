## Diagnóstico

Falla de conectividad o resolución DNS hacia un servidor local inalcanzable (10.0.10.1) que genera múltiples intentos fallidos sin respuesta (S0), sin evidencia confirmada de tráfico malicioso.

## Evaluación del auditor

El análisis de tráfico Zeek evidencia un volumen predominante de consultas DNS (261 registros) originadas en 143.88.255.10 con destino a 10.0.10.1:53 con estado S0 (solicitudes enviadas sin recibir respuesta). Adicionalmente, el host 143.88.0.2 registra consultas sin respuesta hacia servidores raíz públicos. En contraste, las peticiones DNS de 143.88.1.51 y 143.88.1.53 hacia 143.88.1.1 operan con normalidad (SF). No se observan patrones determinantes de exfiltración, tunelado o beaconing malicioso con la evidencia disponible; el comportamiento es consistente con una mala configuración de resolución DNS o servidor inalcanzable.

## Comandos de mitigación propuestos

- resolvectl status
- cat /etc/resolv.conf
- nc -zvu 10.0.10.1 53
- tcpdump -nn -i any host 10.0.10.1 and port 53