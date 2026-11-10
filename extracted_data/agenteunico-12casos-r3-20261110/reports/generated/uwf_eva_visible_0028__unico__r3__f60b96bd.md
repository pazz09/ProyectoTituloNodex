## Diagnóstico

Falla operativa de conectividad o resolución DNS hacia un servidor inalcanzable (10.0.10.1). El host 143.88.255.10 genera ráfagas de consultas DNS cada ~30 segundos que no reciben respuesta (estado S0), sumando 261 intentos fallidos sin indicios de actividad maliciosa.

## Evaluación del auditor

El patrón observado corresponde a un host reintentando periódicamente resolver nombres contra un servidor DNS configurado (10.0.10.1) que no responde a nivel de red (estado S0). La baja frecuencia (~8 solicitudes por minuto) descarta ataques de denegación de servicio (DoS) o fuerza bruta, y no existe evidencia de exfiltración o C2 sobre DNS. El tráfico entre otros equipos (como 143.88.1.51 hacia 143.88.1.1) opera con normalidad con conexiones completadas (SF).

## Comandos de mitigación propuestos

- traceroute 10.0.10.1
- dig @10.0.10.1 test.local
- cat /etc/resolv.conf
- tcpdump -nn -i any host 10.0.10.1 and port 53