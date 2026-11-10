## Diagnóstico

Falla de conectividad recurrente o mala configuración de resolución DNS en el host 143.88.255.10 intentando consultar repetidamente al servidor DNS inaccesible 10.0.10.1 sin obtener respuesta (estado S0).

## Evaluación del auditor

Se observa un patrón sistemático de consultas DNS en intervalos de aproximadamente 30 segundos originadas en la IP 143.88.255.10 dirigidas a 10.0.10.1:53 (UDP) con resultado S0 (sin respuesta). No se identifican dominios exfiltrados ni cargas útiles que confirmen C2 o túnel DNS malicioso en la evidencia disponible, coincidiendo más con un problema operativo de enrutamiento o servicio DNS inalcanzable. El resto de tráfico de la red muestra consultas DNS operando con normalidad (SF) hacia 143.88.1.1.

## Comandos de mitigación propuestos

- ping -c 4 10.0.10.1
- ip route get 10.0.10.1
- resolvectl status
- cat /etc/resolv.conf