## Diagnóstico

Falla de comunicación repetitiva hacia un servidor DNS inalcanzable o mal configurado desde el host 143.88.255.10 hacia 10.0.10.1.

## Evaluación del auditor

El host 143.88.255.10 genera ráfagas de consultas DNS cada 30 segundos dirigidas a la IP privada 10.0.10.1:53 con estado S0 (sin respuesta alguna). Paralelamente, otros equipos de la red resuelven DNS con normalidad (SF) contra 143.88.1.1. El patrón periódico y de bajo volumen es consistente con reintentos automáticos de resolución de nombres o un reenviador mal configurado apuntando a un resolver inactivo, sin evidencia suficiente de tunelado, exfiltración o compromiso malicioso.

## Comandos de mitigación propuestos

- tcpdump -nn -i any host 143.88.255.10 and port 53
- ping -c 4 10.0.10.1
- nc -zvu 10.0.10.1 53