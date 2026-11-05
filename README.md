# Bot de alertas de arbitraje cripto (CriptoYa)

Consulta la API pública de [CriptoYa](https://criptoya.com) cada un minuto, compara
el precio de compra más barato (`totalAsk`) contra el de venta más caro (`totalBid`)
entre todos los exchanges, y cuando el spread supera el umbral manda una alerta
por Telegram y por consola.

No necesita instalar nada: solo Python 3.10 o superior.

## Correr

```bash
python arbitraje.py
```

Una sola pasada para probar:

```bash
python arbitraje.py --once
```

O doble clic en `iniciar.bat`.

## Configuración (`config.json`)

Se crea solo la primera vez. Campos:

| Campo | Qué hace | Default |
|---|---|---|
| `pares` | pares a vigilar (`coin/fiat` según CriptoYa) | usdt, usdc, dai, btc, eth contra ars y contra usd |
| `volumen` | monto en fiat para el cálculo de precios con comisión | 1000 |
| `umbral_pct` | spread mínimo para alertar | 1.5 |
| `intervalo_seg` | cada cuánto consulta | 60 |
| `max_antiguedad_seg` | descarta cotizaciones más viejas que esto | 600 |
| `cooldown_seg` | si una oportunidad se cierra y reabre dentro de este tiempo, no vuelve a avisar | 900 |
| `excluir_por_fiat` | exclusiones solo para un fiat, ej. `{"usd": ["*p2p"]}` para sacar los P2P de los pares en dólares | `{}` |
| `excluir_exchanges` | exchanges a ignorar en alertas, rulos y comandos; `"*p2p"` excluiría todos los P2P. Por defecto solo se excluye Airtm, porque el precio que publica CriptoYa no es el que termina cobrando (verificado: $1.635 publicado contra $1.710 real) | `["airtm"]` |
| `max_desvio_pct` | descarta precios alejados más de esto de la mediana, juzgando cada lado por separado: un exchange que vende barato pero paga poco sigue valiendo para comprar (ofertas basura de P2P quedan afuera); `0` apaga el filtro | 5.0 |
| `max_desvio_usd_pct` | lo mismo para los pares en dólares, más estricto: ahí conviven dólares locales y de cuentas en el exterior (Xapo, Astropay) que cotizan 4 a 6% más bajo sin ser arbitrables | 3.0 |
| `rulos` | buscar rulos de 3 o 4 patas (pesos → dólar/stablecoin → … → pesos) | `true` |
| `umbral_rulo_pct` | rendimiento mínimo de un rulo para alertar | 2.0 |
| `volumen_rulo` | monto en pesos sobre el que se calcula la ganancia del rulo | 100000 |
| `max_patas` | largo máximo del rulo | 4 |
| `mep_spread_pct` | castigo del broker sobre el MEP de referencia de CriptoYa, por lado: al vender dólares vía MEP el rulo usa la referencia menos esto, al comprar la referencia más esto. Ajustalo con lo que te muestre tu broker | 1.0 |
| `p2p_binance_directo` | consultar Binance P2P directo en vez del precio de CriptoYa, filtrado por tus métodos de pago y un monto realista. CriptoYa muestra la mejor oferta de cualquiera, que en dólares suele pedir un banco de Panamá o Wise | `true` |
| `p2p_metodos` | identificadores de Binance de tus métodos de pago (Mercado Pago, Ualá, transferencia bancaria, Santander, Brubank, Naranja X). Evitá los genéricos como `BBVABank`, que matchean vendedores de otros países | ver código |
| `p2p_monto` | monto por fiat con el que se buscan ofertas (las ofertas tienen mínimo y máximo) | usd 500, ars 500000 |
| `capital_ars` / `capital_usdt` | tu capital total para P2P, en pesos o en USDT (USDT manda); la mitad opera en pesos y la mitad en USDT. Dimensiona las ofertas que mira /p2p y las alertas | 0 / 1078 |
| `dolar_aprox` | solo para dimensionar el lado en dólares | 1650 |
| `p2p_plataformas` | plataformas P2P que se consultan directo con tus métodos de pago (Binance, Bybit, OKX, Bitget). Sus precios reemplazan a los de CriptoYa y se buscan cruces entre ellas | las cuatro |
| `umbral_p2p_plataformas_pct` | neto mínimo para alertar un cruce entre plataformas (comprar en una, vender en otra), ya descontado mover el USDT | 0.7 |
| `p2p_transferencia_usd` | costo estimado de mover USDT entre plataformas | 1.0 |
| `p2p_comision_anuncio_pct` | comisión que Binance cobra al que publica un anuncio, por lado; se descuenta dos veces del margen por vuelta. Hoy 0% para USDT en pesos, revisalo en Binance | 0.0 |
| `telegram_token` / `telegram_chat_id` | credenciales de Telegram | vacío |

Si dejás esos campos vacíos, se usan las variables de entorno `TELEGRAM_BOT_TOKEN` y
`TELEGRAM_CHAT_ID`. Lo que está en el archivo siempre tiene prioridad.

## Telegram

1. Hablale a `@BotFather` en Telegram, mandá `/newbot`, elegí nombre, y copiá el token.
2. Abrí un chat con tu bot nuevo y mandale cualquier mensaje.
3. Entrá a `https://api.telegram.org/bot<TOKEN>/getUpdates` en el navegador y copiá
   el número que aparece en `"chat":{"id":...}`.
4. Pegá token y chat id en `config.json` y probá:

```bash
python arbitraje.py --test-telegram
```

Si no configurás Telegram, las alertas salen solo por consola.

## Comandos de Telegram

Con Telegram configurado, el bot también responde mensajes (tipeá `/` y aparece el menú):

| Comando | Qué responde |
|---|---|
| `/arbitraje` | mejor spread de cada par ahora, marcando los que superan el umbral |
| `/rulos` | los 5 mejores rulos de 3 o 4 patas ahora, superen o no el umbral |
| `/p2p` | arbitraje dentro de Binance P2P: las 3 mejores puntas de cada lado (con método de pago, límites y reputación), si hay cruce para comprar y vender ya, a qué precio publicar tus anuncios y cuánto deja, el dólar implícito, y qué hacer paso a paso |
| `/dolar` | todas las formas de comprar dólares ordenadas de más barata a más cara (oficial, blue, MEP, CCL, cripto, tarjeta) y la stablecoin más barata por exchange |
| `/btc` `/eth` `/usdt` `/usdc` `/dai` | los 3 exchanges más baratos para comprar y los 3 mejores para vender, en pesos y en dólares |
| `/capital 160000` o `/capital 1078 usdt` | plan para arrancar con esa plata: reparto entre Mercado Pago y Binance, la primera operación (comprar USDT si tenés pesos, vender la mitad si tenés USDT) y los dos anuncios con precio, cantidad y límites. `/p2p 1078 usdt` analiza con ese tamaño |
| `/umbral` | muestra el umbral de alerta; `/umbral 1.5` lo cambia y lo guarda en `config.json` |
| `/ayuda` | la lista de comandos |

Solo responde al chat configurado en `telegram_chat_id`; a cualquier otro lo ignora.

En el despliegue actual los comandos los responde al instante un webhook en Vercel y las
alertas las manda GitHub Actions cada 10 minutos. Ver [DEPLOY.md](DEPLOY.md).

## ¿Tiene que estar la compu prendida?

Sí: el bot es un proceso Python que corre en tu máquina. Si la apagás o cerrás la
ventana, deja de vigilar. Opciones para que corra solo:

- **Tarea programada de Windows** que lo arranque al iniciar sesión (sigue dependiendo
  de que la compu esté prendida).
- **Un servidor gratuito o barato** (Oracle Cloud Free Tier, Fly.io, Railway, una Raspberry
  Pi en tu casa). Copiás la carpeta, instalás Python y lo corrés igual que acá.
  No usa ninguna librería externa, así que no hay nada más que instalar.

## Rulos (ciclos de 3 o 4 patas)

Además del arbitraje simple, el bot busca ciclos que empiezan y terminan en pesos pasando
por dólares y stablecoins, por ejemplo: comprar dólar oficial en el banco, con esos dólares
comprar USDT en un exchange, y vender el USDT por pesos en otro. Usa el dólar oficial y el
MEP de CriptoYa como patas bancarias, y las cotizaciones de USDT, USDC y DAI contra pesos
y contra dólares como patas cripto. Para cada secuencia elige el mejor exchange por pata.

Las alertas de arbitraje simple funcionan igual que las de rulos: una cuando la oportunidad se abre y otra cuando se cierra (con el máximo que alcanzó y cuánto duró), nunca repetidas en el medio.

Cuando un rulo supera `umbral_rulo_pct` manda una alerta con cada pata, su precio, si es
P2P, y advertencias sobre transferencias y la pata bancaria. Cuando deja de superar el
umbral avisa que se cerró, a cuánto llegó y cuánto duró. El estado vive en `rulos.json`.

Advertencia: estos rulos muestran precios publicados, no ejecuciones garantizadas. Los P2P
dependen de encontrar contraparte, mover dólares entre un exchange y un banco o broker tiene
costos y demoras, y la compra de dólar oficial tiene reglas y límites propios.

## Arbitraje dentro de Binance P2P

Es el arbitraje más limpio: comprás USDT a una persona y se lo vendés a otra, todo dentro de
Binance, sin transferir nada ni pagar comisión de red. El bot consulta las ofertas que aceptan
tus métodos de pago (`p2p_metodos`) y tu monto (`p2p_monto`) y analiza dos cosas:

- **Cruce**: la mejor oferta de compra paga más que lo que pide la mejor de venta. Comprás y
  vendés ya. Alerta si supera `umbral_p2p_cruce_pct` (0,3%).
- **Anuncios**: a qué precio publicar tu propio anuncio de compra y de venta para quedar primero
  en cada punta, y cuánto deja cada vuelta. Alerta si supera `umbral_p2p_anuncio_pct` (1%).

Las alertas avisan una vez al abrir y una al cerrar. En P2P el riesgo es la contraparte: liberá
el USDT solo con la plata acreditada, y preferí vendedores con muchas órdenes y 100% completadas
(se muestran al lado de cada oferta).

## Qué significa la alerta

```
🚨 Arbitraje USDT/ARS  +1.35%
Comprar en binancep2p a 1,669.33
Vender en fiwind a 1,691.90
Ganancia bruta sobre 1,000 ARS: ~14 ARS
```

Los precios ya incluyen las comisiones de trading que reporta CriptoYa, pero **no**
incluyen el costo de mover la cripto o el fiat entre exchanges, ni el tiempo que tarda.
Un spread del 1% suele evaporarse después de retiros y transferencias: subí `umbral_pct`
según tus costos reales.

## Tests

```bash
python -m pytest -q test_arbitraje.py
```
