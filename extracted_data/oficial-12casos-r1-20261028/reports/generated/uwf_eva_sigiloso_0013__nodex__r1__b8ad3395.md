## Diagnóstico

Fallo de configuración operativa / Servicio DNS inalcanzable. El tráfico analizado muestra 244 intentos de resolución DNS desde 143.88.255.10 hacia 10.0.10.1:53 (UDP) con estado de conexión S0 y 0 bytes de respuesta recibidos, lo que confirma que el servidor DNS configurado está caído, inaccesible o bloqueado por enrutamiento/firewall. No se observan patrones de tunelado DNS malicioso, exfiltración ni balizamiento C2.

## Evaluación del auditor

El diagnóstico es correcto. La evidencia muestra un alto volumen de solicitudes DNS periódicas originadas desde 143.88.255.10 dirigidas a 10.0.10.1:53 (UDP) con resultado de conexión S0 (sin respuesta), indicando un fallo de conectividad de red, servidor inalcanzable o error de configuración de nombres. Al mismo tiempo, otros flujos DNS en la red (como consultas hacia 143.88.1.1) completan exitosamente con estado SF. No se observa actividad maliciosa, tunelado, exfiltración ni balizamiento C2.

## Comandos de mitigación propuestos

- ip route get 10.0.10.1
- iptables -I OUTPUT -p udp -d 10.0.10.1 --dport 53 -j ACCEPT
- iptables -I INPUT -p udp -s 10.0.10.1 --sport 53 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
- sed -i '/nameserver 10.0.10.1/a nameserver 1.1.1.1' /etc/resolv.conf
- resolvectl dns $(ip route show default | awk '{print $5}' | head -n1) 10.0.10.1 1.1.1.1 8.8.8.8
- resolvectl flush-caches