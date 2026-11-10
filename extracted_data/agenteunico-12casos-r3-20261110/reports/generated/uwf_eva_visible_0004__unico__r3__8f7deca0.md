## Diagnóstico

Se identifica actividad de escaneo de puertos TCP (Network Service Discovery) originada desde 143.88.18.12 contra 143.88.18.11 afectando múltiples servicios comunes en un lapso breve, además de un flujo continuo y anómalo de consultas DNS sin respuesta (estado S0) desde 143.88.255.10 hacia 10.0.10.1.

## Evaluación del auditor

Los registros de Zeek revelan un sondeo sistemático de puertos TCP típicos (21, 22, 23, 25, 53, 80, 443, 445, 3389, entre otros) desde 143.88.18.12 hacia 143.88.18.11 en estado SH, patrón consistente con reconocimiento de red. Simultáneamente, el host 143.88.255.10 presenta más de 200 conexiones UDP/53 no contestadas (S0) hacia 10.0.10.1, lo que denota fallos de configuración de resolución de nombres o tráfico de sondeo DNS fallido.

## Comandos de mitigación propuestos

- iptables -A INPUT -s 143.88.18.12 -j DROP
- iptables -A FORWARD -s 143.88.18.12 -j DROP