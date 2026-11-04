# Cómo ejecutar un arbitraje cuando el bot avisa

Guía para principiantes. Usa como ejemplo la alerta real del 4 de noviembre de 2026:
comprar USDT en Binance P2P a US$ 1,040 y venderlo en Fiwind a US$ 1,065 (+2,40%).

Esto es información general sobre cómo funciona la mecánica. No es una recomendación
de invertir ni de cuánto poner. Empezá con montos chicos hasta que hayas hecho el
ciclo completo un par de veces.

## La idea en una frase

Comprás una cripto donde está barata, la mandás por blockchain a donde está cara, y la
vendés. La ganancia es la diferencia de precio menos lo que te cobran por mover todo.

## Antes de la primera oportunidad (preparación, se hace una sola vez)

La ventana dura minutos. Si cuando salta la alerta recién vas a crear la cuenta, llegás tarde.

1. **Cuenta verificada en los dos exchanges** que suelen aparecer en las alertas (en tu
   caso Binance, Fiwind, y mirá cuáles se repiten). La verificación de identidad (KYC)
   puede tardar horas o días.
2. **Fondos ya depositados** en el exchange donde se compra. Si la alerta dice "comprar en
   binancep2p", necesitás dólares o pesos disponibles en Binance P2P en ese momento.
3. **Retiros habilitados**: muchos exchanges bloquean retiros 24 a 72 horas después de
   crear la cuenta, cambiar contraseña o agregar un método de pago. Hacé un retiro chico de
   prueba antes de necesitarlo en serio.
4. **Saber qué red usar**: para mover USDT entre exchanges las dos partes tienen que
   soportar la misma red. Las baratas son TRC20 (Tron), Polygon y Solana, que cuestan
   centavos. Ethereum (ERC20) puede costar varios dólares y matar la ganancia. Anotá qué
   redes acepta cada exchange para depositar.

## Cuando llega la alerta: los 5 pasos

Supongamos: comprar en Binance P2P a 1,040, vender en Fiwind a 1,065.

### 1. Confirmá que la oportunidad sigue viva

Abrí los dos exchanges y mirá los precios reales. El bot consulta cada 60 segundos y los
precios P2P cambian rápido. Si el spread ya bajó por debajo de lo que te cuesta mover la
plata, no hagas nada y esperá la próxima.

### 2. Comprá en el exchange barato

En **Binance P2P**: Comprar, elegí USDT, filtrá por tu método de pago, elegí una oferta
con un vendedor con muchas operaciones y buena tasa de completado. Pagás por el método
indicado, marcás "Pagado", y el vendedor libera el USDT a tu billetera de Binance.

Si es un exchange normal (no P2P), es simplemente una orden de compra al precio de mercado.

Reglas de P2P que te evitan estafas:
- Pagá solo por el método que dice la oferta, al titular que dice la oferta.
- Nunca liberes ni marques como pagado antes de ver la plata.
- Si el vendedor te pide hablar fuera de la plataforma, cancelá.

### 3. Mandá la cripto al exchange caro

En **Fiwind**: Depositar, elegí USDT, elegí la red (por ejemplo Polygon o TRC20) y copiá
la dirección.

En **Binance**: Retirar, elegí USDT, pegá la dirección, y elegí **la misma red** que
elegiste en Fiwind. Si las redes no coinciden, la plata se pierde.

La primera vez mandá un monto mínimo de prueba. Cuando lo veas acreditado en Fiwind,
mandá el resto. Una transferencia por Polygon o TRC20 suele tardar entre 1 y 10 minutos.

### 4. Vendé en el exchange caro

Cuando el USDT aparece en Fiwind: Vender USDT. Mirá el precio que te ofrece en ese
momento, no el de la alerta. Si sigue siendo mayor que tu precio de compra más los
costos, confirmá.

### 5. Cerrá la cuenta: calculá lo que te quedó de verdad

Lo que importa es el neto, no el spread que vio el bot:

```
Spread de la alerta:          +2,40%   (sobre 1.000 USD: 24 USD)
Comisión de red del retiro:   -1 USDT aprox. por TRC20 o Polygon
Comisión de retiro a banco:   -lo que cobre Fiwind, revisalo en su tabla de comisiones
Precio que cambió mientras transferías: puede comer todo lo anterior
```

Los precios de CriptoYa ya incluyen la comisión de trading de cada exchange, pero no
incluyen nada de lo anterior.

## Cómo hacen los que lo hacen seguido

En vez de mover la plata en cada oportunidad, tienen **capital en los dos lados**:
USDT en Fiwind y dólares en Binance. Cuando salta la alerta, compran en Binance y venden
en Fiwind **al mismo tiempo**, sin esperar ninguna transferencia. Después, con calma,
rebalancean mandando el USDT de un lado al otro. Eso elimina el riesgo de que el precio
cambie mientras la cripto viaja.

## Qué no es una oportunidad aunque parezca

- **Xapo o Astropay vendiendo USDT a 1,00 contra Fiwind comprando a 1,065**: ese "dólar"
  de Xapo es dinero en una cuenta del exterior, el de Fiwind es dólar local. Convertir
  uno en otro cuesta justamente esa diferencia. El bot filtra estos casos.
- **Un exchange chico con un precio 10% mejor que todos**: suele ser una oferta sin
  liquidez o un dato viejo. El bot también los filtra.
- **Spread del 1% cuando mover la plata cuesta 1,5%**: perdés. Subí `umbral_pct` en
  `config.json` hasta que te quede margen real.

## Riesgos que tenés que conocer

- El precio puede moverse en contra mientras la cripto está en tránsito.
- Elegir mal la red en el retiro pierde los fondos sin vuelta atrás.
- Los exchanges pueden pausar retiros sin aviso.
- En P2P el riesgo de estafa es real; seguí las reglas de arriba.
- Las ganancias pueden tener implicancias impositivas. Consultá con un contador.
