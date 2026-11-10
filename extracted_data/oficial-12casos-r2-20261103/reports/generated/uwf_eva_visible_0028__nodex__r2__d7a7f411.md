## Diagnóstico

Falso positivo de Command and Control (C2). Los 261 eventos registrados desde la IP de origen 143.88.255.10 hacia el resolver DNS interno 10.0.10.1 corresponden a reintentos continuos de conexión sin respuesta (estado S0 / intentos fallidos), provocados por la indisponibilidad o falla de enrutamiento del servidor DNS local. No se observan transferencias de datos bidireccionales, exfiltración ni patrones de balizamiento C2 anómalos. Se recomienda verificar la disponibilidad del servicio DNS en 10.0.10.1 y restaurar la conectividad del resolver para mitigar los reintentos.

## Evaluación del auditor

El diagnóstico es correcto. El tráfico analizado muestra múltiples intentos de conexión UDP al puerto 53 hacia la IP 10.0.10.1 que quedan en estado S0 (sin respuesta del servidor). Se trata de una falla de conectividad de red o indisponibilidad del resolver DNS interno que genera reintentos constantes, descartándose un canal de Command and Control (C2) por la total ausencia de bidireccionalidad, respuestas o payload malicioso.

## Comandos de mitigación propuestos

- ip route get 10.0.10.1
- ping -c 4 10.0.10.1
- nc -zvu -w 3 10.0.10.1 53
- nc -zvt -w 3 10.0.10.1 53
- dig @10.0.10.1 +time=3 +tries=2 healthcheck
- iptables -L -n -v | grep -E '143.88.255.10|10.0.10.1'
- fail2ban-client unban 143.88.255.10 2>/dev/null || true
- iptables -I OUTPUT 1 -p udp -d 10.0.10.1 --dport 53 -j ACCEPT
- iptables -I OUTPUT 1 -p tcp -d 10.0.10.1 --dport 53 -j ACCEPT