import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const tsvPath = path.join(repoRoot, "data", "hokkien_hanri_dict.tsv");
const hanriCharRe = /[\u3400-\u4dbf\u4e00-\u9fff\u{20000}-\u{2ebef}]/gu;

const fallbackGloss = new Map(Object.entries({
  一: "one",
  二: "two",
  三: "three",
  四: "four",
  五: "five",
  六: "six",
  七: "seven",
  八: "eight",
  九: "nine",
  十: "ten",
  百: "hundred",
  千: "thousand",
  萬: "ten thousand",
  个: "classifier; individual",
  的: "possessive marker",
  人: "person; people",
  囝: "child",
  仔: "diminutive suffix",
  兒: "child; son",
  母: "mother",
  父: "father",
  兄: "elder brother",
  弟: "younger brother",
  姊: "elder sister",
  妹: "younger sister",
  家: "home; family",
  口: "mouth",
  手: "hand",
  心: "heart; mind",
  肝: "liver",
  目: "eye",
  耳: "ear",
  頭: "head",
  身: "body",
  面: "face; surface",
  水: "water",
  火: "fire",
  風: "wind",
  雨: "rain",
  天: "sky; day",
  地: "earth; place",
  山: "mountain",
  海: "sea",
  日: "day; sun",
  月: "moon; month",
  年: "year",
  時: "time",
  暝: "night",
  早: "early; morning",
  後: "after; behind",
  前: "before; front",
  上: "above; on",
  下: "below; under",
  中: "middle; in",
  內: "inside",
  外: "outside",
  東: "east",
  西: "west",
  南: "south",
  北: "north",
  大: "big; great",
  小: "small",
  老: "old",
  新: "new",
  好: "good",
  歹: "bad",
  紅: "red",
  白: "white",
  黑: "black",
  青: "blue; green",
  色: "color",
  食: "eat",
  飲: "drink",
  行: "walk; go",
  走: "run; leave",
  來: "come",
  去: "go",
  回: "return",
  轉: "turn; return",
  到: "arrive; reach",
  叫: "call",
  講: "speak; say",
  問: "ask",
  聽: "listen; hear",
  看: "look; watch",
  見: "see",
  知: "know",
  想: "think; want",
  愛: "love; want",
  欲: "want; about to",
  有: "have",
  無: "not have; no",
  是: "be; yes",
  會: "can; meeting",
  做: "do; make",
  用: "use",
  拍: "hit; beat",
  放: "put; release",
  開: "open",
  關: "close",
  買: "buy",
  賣: "sell",
  錢: "money",
  箍: "dollar; ring",
  物: "thing",
  事: "matter; affair",
  啥: "what",
  底: "where; which",
  誰: "who",
  問題: "question; problem",
  世界: "world",
  國: "country",
  省: "province",
  市: "city",
  街: "street",
  路: "road",
  店: "shop",
  厝: "house",
  門: "door",
  房: "room; house",
  學: "learn; study",
  校: "school",
  書: "book",
  字: "character; word",
  話: "speech; language",
  語: "language",
  音: "sound",
  歌: "song",
  戲: "play; drama",
  茶: "tea",
  飯: "rice; meal",
  麵: "noodles",
  米: "rice",
  粉: "flour; powder",
  粿: "rice cake",
  菜: "vegetable; dish",
  肉: "meat",
  魚: "fish",
  蝦: "shrimp",
  雞: "chicken",
  豬: "pig",
  牛: "cow",
  馬: "horse",
  鬼: "ghost",
  神: "deity; spirit",
  王: "king",
  君: "lord; ruler",
  官: "official",
  兵: "soldier",
  頂: "top",
  尾: "tail; end",
  邊: "side",
  款: "type; style",
  種: "kind; type",
  點: "point; dot",
  半: "half",
  全: "whole; all",
  總: "total; general",
  真: "true; really",
  正: "correct; proper",
  直: "straight",
  亂: "chaotic; random",
  平: "flat; ordinary",
  常: "usual; constant",
  便: "convenient",
  當: "when; should",
  然: "so; thus",
  後: "after; behind",
  所: "place; that which",
  過: "pass; exceed",
  起: "rise; start",
  結: "tie; knot",
  婚: "marriage",
  情: "feeling; affection",
  感: "feel; sense",
  覺: "feel; perceive",
  影: "shadow; image",
  要: "important; want",
  緊: "tight; urgent",
  著: "hit; correct; wear",
  插: "insert",
  炒: "fry",
  吵: "noisy; argue",
  煮: "cook; boil",
  洗: "wash",
  穿: "wear; pierce",
  踏: "step on; tread",
  蹛: "stay; live at",
  坐: "sit",
  睏: "sleep",
  病: "illness",
  死: "die",
  生: "life; give birth",
  活: "live; alive",
  煞: "finish; suddenly",
  別: "other; different",
  朋: "friend",
  友: "friend",
  親: "relative; close",
  老師: "teacher",
  學生: "student",
  公司: "company",
  機: "machine; opportunity",
  場: "field; place",
  工: "work",
  車: "vehicle",
  船: "boat",
  電: "electricity",
  腦: "brain",
}));

function hanriChars(value) {
  return [...String(value || "").matchAll(hanriCharRe)].map((match) => match[0]);
}

function hanriOnlyKey(value) {
  return hanriChars(value).join("");
}

function normalizeEnglish(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function mergeGlosses(glosses) {
  const seen = new Set();
  const merged = [];
  for (const gloss of glosses.map(normalizeEnglish).filter(Boolean)) {
    for (const part of gloss.split(";")) {
      const item = normalizeEnglish(part);
      const key = item.toLowerCase();
      if (!item || seen.has(key)) continue;
      seen.add(key);
      merged.push(item);
    }
  }
  return merged.slice(0, 5).join("; ");
}

const raw = fs.readFileSync(tsvPath, "utf8").replace(/^\uFEFF/, "");
const hadFinalNewline = /\r?\n$/.test(raw);
const rows = raw.split(/\r?\n/);
const header = rows.shift();
const kept = [];
const seenRows = new Set();
let duplicateRowsRemoved = 0;

for (const row of rows) {
  if (!row && !hadFinalNewline) continue;
  if (seenRows.has(row)) {
    duplicateRowsRemoved += 1;
    continue;
  }
  seenRows.add(row);
  kept.push(row);
}

const parsed = kept.map((line) => {
  const columns = line.split("\t");
  while (columns.length < 5) columns.push("");
  return columns;
});

const exactGlossByHanri = new Map();
const exactGlossByHanriOnly = new Map();
const singleCharGloss = new Map(fallbackGloss);

for (const columns of parsed) {
  const [reading, hanri, , , english] = columns;
  if (!reading || reading.startsWith("#")) continue;
  const gloss = normalizeEnglish(english);
  if (!gloss) continue;

  if (!exactGlossByHanri.has(hanri)) {
    exactGlossByHanri.set(hanri, gloss);
  }

  const key = hanriOnlyKey(hanri);
  if (key) {
    if (!exactGlossByHanriOnly.has(key)) {
      exactGlossByHanriOnly.set(key, gloss);
    }
    if ([...key].length === 1 && !singleCharGloss.has(key)) {
      singleCharGloss.set(key, gloss);
    }
  }
}

let copiedSameHanri = 0;
let copiedHanriOnly = 0;
let filledFromComponents = 0;

for (const columns of parsed) {
  const [reading, hanri] = columns;
  if (!reading || reading.startsWith("#") || normalizeEnglish(columns[4])) continue;

  let gloss = exactGlossByHanri.get(hanri);
  if (gloss) {
    copiedSameHanri += 1;
  } else {
    const hanriOnly = hanriOnlyKey(hanri);
    gloss = exactGlossByHanriOnly.get(hanriOnly);
    if (gloss) {
      copiedHanriOnly += 1;
    } else {
      const chars = [...hanriOnly];
      const charGlosses = chars.map((char) => singleCharGloss.get(char)).filter(Boolean);
      if (charGlosses.length) {
        gloss = mergeGlosses(charGlosses);
        filledFromComponents += 1;
      }
    }
  }

  if (gloss) {
    columns[4] = gloss;
  }
}

const output = [header, ...parsed.map((columns) => columns.slice(0, 5).join("\t"))].join("\n") + "\n";
fs.writeFileSync(tsvPath, output, "utf8");

const remainingBlankHanri = parsed.filter((columns) => {
  const [reading, hanri, , , english] = columns;
  return reading && !reading.startsWith("#") && hanriOnlyKey(hanri) && !normalizeEnglish(english);
}).length;

console.log(JSON.stringify({
  duplicateRowsRemoved,
  copiedSameHanri,
  copiedHanriOnly,
  filledFromComponents,
  remainingBlankHanri,
}, null, 2));
