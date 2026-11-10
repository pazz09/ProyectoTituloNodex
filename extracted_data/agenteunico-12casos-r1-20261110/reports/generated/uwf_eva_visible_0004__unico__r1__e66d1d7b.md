## Diagnóstico

Se detecta actividad maliciosa de reconocimiento de red (escaneo de puertos TCP) originada por la IP 143.88.18.12 contra el host 143.88.18.11, abarcando múltiples puertos comunes (21, 22, 23, 80, 443, 445, 3389, etc.) en un lapso de dos segundos con estado SH. Adicionalmente, se observa un volumen persistente de solicitudes DNS sin respuesta (estado S0) desde 143.88.255.10 hacia 10.0.10.1, indicativo de servidor inalcanzable o sondeo.

## Evaluación del auditor

El patrón de conexiones TCP con flags SYN/FIN (estado SH en Zeek) dirigidas consecutivamente a una amplia gama de puertos en 143.88.18.11 confirma un escaneo de puertos horizontal/vertical típico de herramientas de reconocimiento como Nmap. Esto constituye un incidente de seguridad en fase de descubrimiento lateral.

## Comandos de mitigación propuestos

- iptables -A INPUT -s 143.88.18.12 -j DROP
- iptables -A FORWARD -s 143.88.18.12 -j DROP