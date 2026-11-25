# CAN controllers: SPI chips, MCU peripherals, boards, libraries

A CAN node is **controller** (protocol logic) plus **transceiver** (bus driver). Controllers are covered here; transceivers in `transceivers.md`. Electrical limits quoted here are the headline figures: confirm against the current datasheet before committing a design.

Contents
- [Choosing](#choosing)
- [MCP2515](#mcp2515)
- [MCP2517FD / MCP2518FD](#mcp2517fd--mcp2518fd)
- [TCAN4550](#tcan4550)
- [SJA1000](#sja1000)
- [ESP32 TWAI](#esp32-twai)
- [STM32 bxCAN](#stm32-bxcan)
- [STM32 FDCAN and other M_CAN parts](#stm32-fdcan-and-other-m_can-parts)
- [Other MCU families](#other-mcu-families)
- [Raspberry Pi and Linux SBCs](#raspberry-pi-and-linux-sbcs)
- [Common boards and what is on them](#common-boards-and-what-is-on-them)
- [Firmware libraries](#firmware-libraries)
- [Acceptance filters](#acceptance-filters)

## Choosing

| Situation | Use |
|---|---|
| MCU already has CAN (ESP32, STM32, Teensy 4, SAM C21/E5x, Uno R4) | the built-in controller plus a transceiver. Cheaper, faster and more reliable than SPI |
| MCU without CAN, classical CAN only, low to moderate traffic | MCP2515 |
| MCU without CAN, CAN FD or a busy bus | MCP2518FD (or MCP251863 with built-in transceiver) |
| RP2040 / RP2350 | `can2040` software CAN over PIO (classical, up to 1 Mbit/s) or an MCP2518FD |
| CAN FD with one chip including transceiver and LDO, automotive supply | TCAN4550 |
| Linux SBC | MCP2518FD HAT (`mcp251xfd` driver) or a USB adapter; MCP2515 HAT for classical |
| Sniffing a busy vehicle bus with an Arduino Uno + MCP2515 | expect dropped frames; use a filter, a faster MCU, or a USB adapter |

Which controllers do CAN FD: MCP2517FD/2518FD/251863, TCAN4550, STM32 FDCAN (G0, G4, H5, H7, L5, U5), SAM C21/E51/E54, Teensy 4.x CAN3, NXP S32K/i.MX RT FlexCAN-FD, ESP32-C5. Classical only: MCP2515, SJA1000, ESP32/S2/S3/C3/C6/H2/P4 TWAI, STM32 bxCAN (F0/F1/F2/F3/F4/F7/L4), Uno R4, Due, can2040.

## MCP2515

Stand-alone classical CAN 2.0B controller with SPI.

- Supply 2.7-5.5 V. SPI up to 10 MHz, modes 0,0 and 1,1. Crystal up to 40 MHz at 5 V (lower at 3.3 V); modules ship with 8 or 16 MHz.
- 3 transmit buffers, 2 receive buffers (RXB0 with 2 filters, RXB1 with 4 filters), 2 masks. One interrupt pin, plus optional RXnBF and TXnRTS pins.
- Modes (CANCTRL REQOP): configuration, normal, sleep, listen-only, loopback. It powers up in configuration mode; bit timing (CNF1-3) and filters can only be written there. One-shot mode is CANCTRL.OSM.
- The MCP25625 is the same controller with an MCP2562-class transceiver in the package.

SPI instructions: RESET `0xC0`, READ `0x03`, WRITE `0x02`, BIT MODIFY `0x05`, READ STATUS `0xA0`, RX STATUS `0xB0`, READ RX BUFFER `0x90`/`0x94`, LOAD TX BUFFER `0x40`/`0x42`/`0x44`, RTS `0x81`/`0x82`/`0x84`.

Key registers: CANSTAT `0x0E`, CANCTRL `0x0F`, CNF3 `0x28`, CNF2 `0x29`, CNF1 `0x2A`, CANINTE `0x2B`, CANINTF `0x2C`, EFLG `0x2D`, TEC `0x1C`, REC `0x1D`, RXB0CTRL `0x60`, RXB1CTRL `0x70`, TXB0CTRL `0x30`.

What goes wrong:
- **Crystal mismatch**: code says 16 MHz, board has 8 MHz. Everything initialises, nothing is received. Read the crystal marking. See `bit-timing.md`.
- **The blue "MCP2515 + TJA1050" module is a 5 V board.** The TJA1050 needs 5 V. Powered from 3.3 V the bus side does not work; powered from 5 V the SO/INT pins drive 5 V into the MCU, and the MCP2515's own inputs (SCK, SI, CS) need at least 0.7 x VDD = 3.5 V for a high, which a 3.3 V MCU does not guarantee. It often works on the bench and then fails with temperature or on another board. With an ESP32, Pico or other 3.3 V MCU, do one of: replace the transceiver with a 3.3 V part and run the whole board at 3.3 V (the MCP2515 itself runs from 2.7 V); use a 3.3 V-native module; or translate all five signals, down for SO and INT and up for SCK, SI and CS.
- **Receive overflow**: two buffers fill within about 250 us at 500 kbit/s. Polling `readMessage()` from `loop()` loses frames on a busy bus. Use the INT pin, enable rollover (RXB0CTRL.BUKT), set filters to drop what is not needed, and read with the READ RX BUFFER instruction (it clears the flag in the same transaction). EFLG bits RX0OVR/RX1OVR record overflows.
- **Library leaves the chip in loopback or config mode**: `coryjfowler/MCP_CAN_lib` `begin()` ends in loopback; call `setMode(MCP_NORMAL)` or `setMode(MCP_LISTENONLY)`. With `autowp/arduino-mcp2515` call `setNormalMode()` or `setListenOnlyMode()` after `setBitrate()`.
- Init fails: SPI wiring or chip select, missing reset, or SPI clock too fast for long jumper wires (try 1 MHz).
- Termination jumper J1 left on when the module is not at a bus end.

```cpp
// autowp/arduino-mcp2515: sniff at 500 kbit/s with an 8 MHz module
#include <SPI.h>
#include <mcp2515.h>
MCP2515 can(10);                       // CS pin
void setup() {
  Serial.begin(115200);
  can.reset();
  can.setBitrate(CAN_500KBPS, MCP_8MHZ);   // second argument must match the crystal
  can.setListenOnlyMode();                 // setNormalMode() to transmit and ACK
}
void loop() {
  struct can_frame f;
  if (can.readMessage(&f) == MCP2515::ERROR_OK) {
    Serial.print(f.can_id & CAN_EFF_MASK, HEX);   // bit 31 of can_id marks a 29-bit ID
    for (int i = 0; i < f.can_dlc; i++) { Serial.print(' '); Serial.print(f.data[i], HEX); }
    Serial.println();
  }
}
```

## MCP2517FD / MCP2518FD

Stand-alone CAN FD controllers with SPI. The MCP2518FD is the current part (adds a low-power mode and fixes errata of the 2517FD); prefer it for new work. The **MCP251863** is an MCP2518FD with an ATA6563 transceiver in one package.

- Classical CAN and CAN FD up to 8 Mbit/s data rate. SPI up to 20 MHz. Supply 2.7-5.5 V.
- Clock: 40 MHz or 20 MHz crystal/oscillator, or 4 MHz with the internal 10x PLL. 40 MHz gives the cleanest FD timings.
- Memory is 2 kB of RAM that you divide into a transmit event FIFO (TEF), a transmit queue (TXQ) and up to 31 FIFOs, each configurable as TX or RX with its own depth and payload size. 32 filter/mask pairs, each pointing at a FIFO. A 64-byte payload with timestamp costs 76 bytes of RAM per message, so the 2 kB limits depth quickly.
- Registers are 32-bit, addressed over SPI with a 12-bit address. SPI commands: RESET `0x0`, READ `0x3`, WRITE `0x2`, and CRC-protected READ_CRC `0xB` / WRITE_CRC `0xA`. Use the CRC variants on wiring longer than a few centimetres.
- Modes: configuration, normal FD, normal CAN 2.0, listen-only, restricted, internal and external loopback, sleep.

What goes wrong: wrong oscillator setting (`MCP251XFD` drivers must be told 40 vs 20 MHz); SPI clock above about half of SYSCLK; marginal SPI wiring causing corrupt reads (use CRC commands, short wires, lower SPI speed); TDC not configured for data rates of 2 Mbit/s and above; transceiver standby pin (wired to a GPIO on many boards) left high; RAM budget exceeded in FIFO configuration.

Libraries: `pierremolinaro/acan2517FD` (Arduino, covers both parts, MIT), Microchip's `MCP25xxFD` C driver, Linux `mcp251xfd` (in-tree, the best-tested implementation), Zephyr `mcp251xfd`.

## TCAN4550

TI system basis chip: Bosch M_CAN CAN FD controller + CAN FD transceiver + LDO, behind SPI (up to 18 MHz).

- CAN FD up to 8 Mbit/s (5 Mbit/s for some variants). 20 or 40 MHz crystal.
- Runs from battery voltage (VSUP up to about 30 V) and can supply the MCU from its 5 V LDO. Wake pin, INH, watchdog, failsafe.
- Software model is the standard M_CAN register set (same as STM32 FDCAN), so bit-timing and message-RAM concepts carry over. Linux driver `tcan4x5x`.
- Gotchas: it starts in standby and must be put in normal mode over SPI; the watchdog and failsafe must be handled or disabled; message RAM must be configured before use.

## SJA1000

NXP's classical controller with a parallel bus. Rarely designed in today, but it is the ancestor that matters: the ESP32 TWAI peripheral is SJA1000-derived, PC adapters and industrial cards still use it, and its register model (BTR0/BTR1, acceptance code and mask, PeliCAN mode) appears across Linux drivers and tool documentation. 64-byte receive FIFO, one transmit buffer, clock divided by 2 before the prescaler.

## ESP32 TWAI

Espressif calls its CAN controller TWAI. It needs an external 3.3 V-compatible transceiver. TX and RX route to almost any GPIO; avoid strapping, flash and USB pins for the board in use.

| Chip | Controllers | CAN FD |
|---|---|---|
| ESP32 (classic), S2, S3, C3, H2 | 1 | no |
| ESP32-C6 | 2 | no |
| ESP32-P4 | 3 | no |
| ESP32-C5 | 2 | yes |
| ESP32-C2, ESP8266 | none | - |

Check the ESP-IDF TWAI page for the exact chip before relying on this table for newer parts.

A classical-only TWAI controller on a CAN FD bus cannot decode FD frames and, in normal mode, destroys them with error flags.

**Two driver generations.** The legacy driver (`driver/twai.h`: one global instance, queue based) is what most existing code and Arduino libraries use. ESP-IDF 5.5 and later add a handle-based driver (`esp_twai.h` + `esp_twai_onchip.h`, component `esp_driver_twai`) that supports several controllers and CAN FD; new ESP-IDF projects should use it. Check which one the project already uses before writing code, and do not mix them.

Legacy driver:

```c
#include "driver/twai.h"

twai_general_config_t g = TWAI_GENERAL_CONFIG_DEFAULT(GPIO_NUM_5, GPIO_NUM_4, TWAI_MODE_LISTEN_ONLY); // TX, RX
g.rx_queue_len = 64;
twai_timing_config_t  t = TWAI_TIMING_CONFIG_500KBITS();
twai_filter_config_t  f = TWAI_FILTER_CONFIG_ACCEPT_ALL();
ESP_ERROR_CHECK(twai_driver_install(&g, &t, &f));
ESP_ERROR_CHECK(twai_start());

twai_message_t rx;
if (twai_receive(&rx, pdMS_TO_TICKS(100)) == ESP_OK) {
    // rx.identifier, rx.extd, rx.rtr, rx.data_length_code, rx.data[]
}

twai_message_t tx = { .identifier = 0x7DF, .data_length_code = 8,
                      .data = {0x02, 0x01, 0x0C, 0, 0, 0, 0, 0} };
twai_transmit(&tx, pdMS_TO_TICKS(100));        // needs TWAI_MODE_NORMAL and another node to ACK
```

- Modes: `TWAI_MODE_NORMAL`, `TWAI_MODE_LISTEN_ONLY`, `TWAI_MODE_NO_ACK` (self-test: transmit succeeds without an ACK; use with `.self = 1` for a one-board loopback test).
- Watch alerts: enable `TWAI_ALERT_BUS_OFF | TWAI_ALERT_ERR_PASS | TWAI_ALERT_RX_QUEUE_FULL | TWAI_ALERT_TX_FAILED` in `alerts_enabled`, read with `twai_read_alerts()`. After bus-off call `twai_initiate_recovery()`, wait for `TWAI_ALERT_BUS_RECOVERED`, then `twai_start()`.
- `twai_get_status_info()` returns state, TEC, REC and queue counts: print it when debugging.
- `twai_receive()` returning `ESP_ERR_TIMEOUT` forever with the right bitrate usually means the RX pin or the transceiver (standby pin, supply voltage).

New driver:

```c
#include "esp_twai.h"
#include "esp_twai_onchip.h"

static bool on_rx(twai_node_handle_t node, const twai_rx_done_event_data_t *ev, void *ctx) {
    uint8_t buf[8];
    twai_frame_t f = { .buffer = buf, .buffer_len = sizeof(buf) };
    if (twai_node_receive_from_isr(node, &f) == ESP_OK) {
        // f.header.id, f.header.ide, f.header.dlc, buf: copy to a queue, this is ISR context
    }
    return false;
}

twai_onchip_node_config_t cfg = {
    .io_cfg = { .tx = GPIO_NUM_5, .rx = GPIO_NUM_4,
                .quanta_clk_out = GPIO_NUM_NC, .bus_off_indicator = GPIO_NUM_NC },
    .bit_timing = { .bitrate = 500000 },
    // .data_timing = { .bitrate = 2000000 },   // CAN FD capable chips only
    .fail_retry_cnt = -1,                       // -1 = retry forever, 0 = one-shot
    .tx_queue_depth = 8,
    // .flags.enable_listen_only = 1,
};
twai_node_handle_t node;
ESP_ERROR_CHECK(twai_new_node_onchip(&cfg, &node));
twai_event_callbacks_t cbs = { .on_rx_done = on_rx };   // also on_tx_done, on_state_change, on_error
ESP_ERROR_CHECK(twai_node_register_event_callbacks(node, &cbs, NULL));   // before enable
ESP_ERROR_CHECK(twai_node_enable(node));

uint8_t d[8] = {0x02, 0x01, 0x0C};
twai_frame_t tx = { .header = { .id = 0x7DF, .dlc = 8 }, .buffer = d, .buffer_len = 8 };
ESP_ERROR_CHECK(twai_node_transmit(node, &tx, 100));
```

Reception happens inside the `on_rx_done` callback (ISR context: no blocking calls, no logging). Bus-off arrives through `on_state_change`; recover with `twai_node_recover()`. Filters: `twai_node_config_mask_filter()`. State and counters: `twai_node_get_info()`. Field names evolve between IDF releases, so open the header of the installed version when a struct member does not compile.

Arduino-ESP32: call the legacy IDF driver directly (most robust), or use `handmade0octopus/ESP32-TWAI-CAN`, `collin80/esp32_can`, or `pierremolinaro/ACAN_ESP32`. `sandeepmistry/arduino-CAN` is unmaintained and breaks on newer cores and chips.

Classic ESP32 notes: bitrates below 25 kbit/s need chip revision 2 or later; hardware errata are worked around by the driver (keep the `CONFIG_TWAI_ERRATA_FIX_*` options enabled).

## STM32 bxCAN

Classical CAN on F0, F1, F2, F3, F4, F7, L4.

- 3 transmit mailboxes, 2 receive FIFOs of 3 messages each, 14 filter banks (28 shared on dual-CAN parts).
- Clock is PCLK1. `Mode`: `CAN_MODE_NORMAL`, `CAN_MODE_LOOPBACK`, `CAN_MODE_SILENT`, `CAN_MODE_SILENT_LOOPBACK`.
- **Nothing is received until at least one filter bank is configured and enabled**, even to accept everything. This is the number one bxCAN question.
- On dual-CAN parts CAN2 is a slave of CAN1: CAN1's clock must be enabled, and CAN2's filters start at `SlaveStartFilterBank` (14 by default).
- F103: CAN and USB share a RAM block and cannot be active together. F103 CAN pins need remapping (PB8/PB9) on many boards.
- `AutoBusOff = ENABLE` recovers from bus-off automatically. `AutoRetransmission = DISABLE` gives one-shot.
- `HAL_CAN_Start()` returns `HAL_ERROR`/times out when the RX pin never sees a recessive level: transceiver missing, unpowered, or in standby. Test the software alone with `CAN_MODE_LOOPBACK`.

```c
CAN_FilterTypeDef f = {0};
f.FilterBank = 0;
f.FilterMode = CAN_FILTERMODE_IDMASK;
f.FilterScale = CAN_FILTERSCALE_32BIT;
f.FilterMaskIdHigh = 0; f.FilterMaskIdLow = 0;      // mask 0 = accept all
f.FilterFIFOAssignment = CAN_RX_FIFO0;
f.FilterActivation = ENABLE;
HAL_CAN_ConfigFilter(&hcan1, &f);
HAL_CAN_Start(&hcan1);
HAL_CAN_ActivateNotification(&hcan1, CAN_IT_RX_FIFO0_MSG_PENDING | CAN_IT_BUSOFF | CAN_IT_ERROR);
// void HAL_CAN_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *h) { HAL_CAN_GetRxMessage(h, CAN_RX_FIFO0, &hdr, data); }
```

In 32-bit filter registers a standard ID sits at bits 31-21 (`id << 21`, so `FilterIdHigh = id << 5`); an extended ID is `(id << 3) | CAN_ID_EXT`.

## STM32 FDCAN and other M_CAN parts

FDCAN (G0, G4, H5, H7, L5, U5) is Bosch M_CAN IP, as are TCAN4550 and SAM C21/E5x.

- Classical and CAN FD. Filters, RX FIFOs/buffers and TX buffers live in a **message RAM**. On G0/G4/L5/U5 the layout is fixed (28 standard and 8 extended filters, two RX FIFOs of 3, 3 TX buffers per instance). On H7 you size each section yourself and must not overlap instances.
- The kernel clock is selected in RCC and is separate from the bus clock; 40 or 80 MHz makes FD timing easy.
- `FrameFormat`: `FDCAN_FRAME_CLASSIC`, `FDCAN_FRAME_FD_NO_BRS`, `FDCAN_FRAME_FD_BRS`. Each transmitted frame also carries its own `FDFormat` and `BitRateSwitch` flags.
- Unlike bxCAN, frames that match no filter are handled by the global filter: call `HAL_FDCAN_ConfigGlobalFilter()` to accept or reject non-matching frames. Then `HAL_FDCAN_Start()` and `HAL_FDCAN_ActivateNotification(..., FDCAN_IT_RX_FIFO0_NEW_MESSAGE, 0)`.
- Transmitter delay compensation: `HAL_FDCAN_ConfigTxDelayCompensation()` + `HAL_FDCAN_EnableTxDelayCompensation()` before start, for data rates of 2 Mbit/s and above.
- `DataLength` uses DLC codes, not byte counts (`FDCAN_DLC_BYTES_12` = 9).

## Other MCU families

| Family | CAN | Notes |
|---|---|---|
| Teensy 3.x / 4.x | FlexCAN | `tonton81/FlexCAN_T4`. Teensy 4.x: CAN1 and CAN2 classical, CAN3 CAN FD. Needs external transceivers |
| NXP Kinetis, S32K, i.MX RT, LPC | FlexCAN / FlexCAN-FD | mailbox based; automotive mainstream |
| Microchip SAM C21, E51, E54 | M_CAN, CAN FD | Adafruit Feather M4 CAN is a SAME51 |
| Microchip dsPIC33, PIC18 K80/K83, PIC32 | ECAN / CAN FD on newer parts | |
| Arduino Uno R4 (Renesas RA4M1) | 1 classical | `Arduino_CAN` built in; needs a transceiver on D4/D5 |
| Arduino Due (SAM3X) | 2 classical | `collin80/due_can` |
| Raspberry Pi Pico RP2040/RP2350 | none in hardware | `KevinOConnor/can2040` (PIO, classical, 1 Mbit/s) or SPI controller |
| AVR (Uno, Nano, Mega), ESP8266, nRF52 | none | SPI controller. AT90CAN is the AVR exception |
| GD32/CH32/APM32 "STM32-compatible" parts | bxCAN-like | filter and timing quirks differ from genuine parts; test loopback first |

## Raspberry Pi and Linux SBCs

Enable SPI and add an overlay in `/boot/firmware/config.txt` (older images: `/boot/config.txt`):

```
dtparam=spi=on
dtoverlay=mcp2515-can0,oscillator=16000000,interrupt=25
dtoverlay=mcp251xfd,spi0-0,oscillator=40000000,interrupt=25
```

`oscillator` must equal the crystal on the HAT (8, 12 and 16 MHz MCP2515 boards all exist; a wrong value gives a silently wrong bitrate). `interrupt` is the GPIO wired to INT. Then:

```bash
sudo ip link set can0 up type can bitrate 500000 restart-ms 100
sudo ip link set can0 up type can bitrate 500000 dbitrate 2000000 fd on     # mcp251xfd
dmesg | grep -i -E "mcp25|can"          # confirm the chip was detected
```

"Cannot find device can0": the overlay did not load or the chip did not answer over SPI. See `tools.md` for the rest of SocketCAN.

## Common boards and what is on them

| Board | Controller | Transceiver | Notes |
|---|---|---|---|
| Blue "MCP2515 CAN module" | MCP2515, usually 8 MHz | TJA1050 | 5 V only; termination jumper J1 |
| Seeed CAN-BUS Shield V2, SparkFun CAN-BUS Shield | MCP2515, 16 MHz | MCP2551 | 5 V Arduino shields; DB9 pinouts differ between them |
| Adafruit CAN Pal | none (transceiver only) | TJA1051T/3 | 3.3 V logic, onboard 5 V boost |
| Adafruit Feather M4 CAN | SAME51 built in | TCAN1051 | CAN FD capable |
| Adafruit RP2040 CAN Bus Feather | MCP25625 | integrated | classical |
| SN65HVD230 breakout ("CJMCU-230", Waveshare SN65HVD230 board) | none | SN65HVD230 | 3.3 V; usually has a fixed 120 ohm resistor on board |
| Waveshare RS485 CAN HAT | MCP2515, 12 MHz (older: 8 MHz) | SN65HVD230 | Raspberry Pi |
| Waveshare 2-CH CAN FD HAT, Seeed 2-channel CAN FD shield | MCP2518FD (early Seeed: MCP2517FD), 40 MHz | FD transceivers | Raspberry Pi, `mcp251xfd` |
| PiCAN2 / PiCAN FD (SK Pang) | MCP2515 16 MHz / MCP2518FD | MCP2551 / FD part | Raspberry Pi |
| LilyGO T-CAN485, Waveshare ESP32-S3 CAN boards, Olimex ESP32-EVB | ESP32 TWAI | onboard | check the schematic for pins and a transceiver enable/standby GPIO |
| M5Stack CAN units | host's controller | isolated CA-IS3050G | transceiver only, isolated |
| Teensy 4.x + transceiver breakout | FlexCAN | add your own | CAN FD on CAN3 |
| CANable / CANable 2.0 and clones | STM32F042/F072 / STM32G431 | onboard | USB adapters, see `tools.md` |
| Macchina M2 / A0 | SAM3X (Due-class) / ESP32 | onboard | vehicle-interface boards with OBD connectors |

Board revisions change parts. Read the crystal marking and the transceiver marking on the board in hand.

## Firmware libraries

| Library | Target | Notes |
|---|---|---|
| `autowp/arduino-mcp2515` | MCP2515 on Arduino | simple, SocketCAN-style `can_frame`; needs the crystal constant |
| `coryjfowler/MCP_CAN_lib` | MCP2515 | widely copied; `begin()` leaves loopback mode |
| `pierremolinaro/acan2515`, `acan2517FD`, `ACAN_ESP32`, `ACAN_T4` | MCP2515, MCP2517/18FD, ESP32, Teensy 4 | computes bit timing from the clock and checks it; good diagnostics |
| `adafruit/Adafruit_MCP2515`, CircuitPython `canio` | Adafruit boards | |
| `Seeed-Studio/Seeed_Arduino_CAN` | MCP2515 and MCP2518FD shields | |
| `tonton81/FlexCAN_T4` | Teensy 3.x/4.x | classical and FD |
| `collin80/esp32_can`, `due_can`, `can_common` | ESP32, Due | the SavvyCAN/GVRET ecosystem |
| `KevinOConnor/can2040` | RP2040/RP2350 | software CAN on PIO |
| ESP-IDF `esp_driver_twai`, STM32 HAL/LL, Zephyr CAN API, MicroPython/CircuitPython CAN modules | vendor and RTOS drivers | Zephyr gives one API across MCU CAN, MCP2515, MCP251xFD and TCAN4x5x |
| Rust `embedded-can` traits with `bxcan`, `fdcan`, `mcp2515` crates | Rust embedded | |
| Linux in-tree drivers: `mcp251x`, `mcp251xfd`, `m_can`/`tcan4x5x`, `flexcan`, `sja1000`, `gs_usb`, `peak_usb`, `kvaser_usb`, `slcan` | SocketCAN | |

Before recommending a library for new work, check its repository for recent activity and its licence: several popular Arduino CAN libraries are unmaintained.

## Acceptance filters

All controllers filter the same way: a frame is accepted when `(received_id & mask) == (filter_id & mask)`. A mask bit of 1 means "this bit must match".

- Accept everything: mask 0.
- One ID: mask all ones (0x7FF or 0x1FFFFFFF).
- OBD-II responses 0x7E8-0x7EF: filter 0x7E8, mask 0x7F8.
- A J1939 PGN from any source: filter `pgn << 8`, mask `0x03FFFF00` (PDU2; includes the two data-page bits) on extended IDs.

**SJA1000-style controllers, including the ESP32 legacy driver, invert the mask: 1 means "don't care".** There the ID is also left-aligned: for a standard ID in single-filter mode, `acceptance_code = id << 21` and `acceptance_mask = ~(0x7FF << 21)`; for an extended ID, `id << 3` and `~(0x1FFFFFFF << 3)`. Accept-all is code 0, mask 0xFFFFFFFF.

When "nothing is received", remove all filtering first. Filters are a frequent cause.
