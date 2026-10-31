// Shows the current command byte on the 8x13 matrix. Bitmaps mirror the
// virtual matrix in static/index.html.
#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>

const int ROWS = 8;
const int COLS = 13;
const uint8_t LIT = 7;  // brightness at 3 grayscale bits (0-7)

Arduino_LED_Matrix matrix;
uint8_t frame[ROWS * COLS] = {0};
volatile int mode = '0';

const char* const BEACON[ROWS] = {
  "##....#....##", "#.....#.....#", "#.....#.....#", "#.....#.....#",
  "#.....#.....#", "#...........#", "#.....#.....#", "##....#....##"};
const char* const CHECK[ROWS] = {
  ".............", "..........#..", ".........##..", "#.......##...",
  ".#.....##....", "..#...##.....", "...#.##......", "....##......."};

void setPixel(int r, int c) {
  if (r >= 0 && r < ROWS && c >= 0 && c < COLS) frame[r * COLS + c] = LIT;
}

void drawBitmap(const char* const rows[]) {
  for (int r = 0; r < ROWS; r++)
    for (int c = 0; c < COLS; c++)
      if (rows[r][c] == '#') setPixel(r, c);
}

void drawLoadBars(int t) {
  for (int b = 0; b < 7; b++) {
    int h = min(ROWS, 1 + b + t % 3);
    for (int r = 0; r < h; r++) setPixel(ROWS - 1 - r, b * 2);
  }
}

// Top half: <<< moving left. Bottom half: >>> moving right.
void drawLaneArrows(int t) {
  int sh = t % 4;
  for (int k = 0; k < 4; k++) {
    int left = ((k * 4 - sh) % 16 + 16) % 16 - 2;
    int right = ((k * 4 + sh) % 16 + 16) % 16 - 2;
    for (int i = 0; i < 4; i++) {
      setPixel(i, left + 3 - i);
      setPixel(4 + i, right + i);
    }
  }
}

void drawCheckerboard(int t) {
  for (int r = 0; r < ROWS; r++)
    for (int c = 0; c < COLS; c++)
      if ((r + c + t) % 2 == 0) setPixel(r, c);
}

void render(int m, int t) {
  memset(frame, 0, sizeof(frame));
  switch (m) {
    case 'W': if (t % 2 == 0) drawBitmap(BEACON); break;
    case 'G': drawLoadBars(t); break;
    case 'T': drawLaneArrows(t); break;
    case 'I': drawCheckerboard(t); break;
    default: drawBitmap(CHECK); break;
  }
}

void set_mode(int code) {
  mode = code;
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);  // active low: HIGH is off
  matrix.begin();
  matrix.setGrayscaleBits(3);
  matrix.clear();
  Bridge.begin();
  Bridge.provide("set_mode", set_mode);
}

void loop() {
  static int tick = 0;
  int m = mode;
  render(m, tick++);
  matrix.draw(frame);
  digitalWrite(LED_BUILTIN, m == 'G' ? LOW : HIGH);  // simulated relay
  delay(m == 'W' ? 500 : 350);
}
