App Lab app for the UNO Q. Serves the board API from SPEC.md on port 8080 and
draws the command byte on the LED matrix.

1. Copy this folder to the board, e.g. `scp -r uno_q_edge arduino@<board-ip>:ArduinoApps/opencity-edge`
2. Open it in App Lab and press Run.
3. Set `BOARD_URL=http://<board-ip>:8080` in the laptop's `.env`.
4. Check it from the laptop: `python hardware_client.py W`

No board? Run `python uno_q_edge/python/main.py` and set
`BOARD_URL=http://127.0.0.1:8080`. Bytes are logged instead of drawn.
