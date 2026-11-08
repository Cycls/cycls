// Which way text with Arabic and English in it reads, as the mobile app decides it. Arabic leads once a third of its
// words are Arabic (words, as letters undercount Arabic's unwritten vowels): an Arabic sentence quotes English terms
// far more often than the reverse. Code, math, links, addresses, paths and file names don't vote.
const RTL = /[֐-ࣿיִ-﷿ﹰ-﻿]/;
const LTR = /[A-Za-zÀ-ɏ]/;
const STRONG = new RegExp(`${RTL.source}|${LTR.source}`);
const QUIET = /```[\s\S]*?(?:```|$)|\$\$[\s\S]*?(?:\$\$|$)|`[^`\n]*`|\]\([^)\s]*\)|https?:\/\/\S+|\S+@\S+\.\S+|\S*[/\\]\S*|\S+\.[A-Za-z0-9]{1,5}(?![A-Za-z0-9])/g;

export function dirOf(s: string): "rtl" | "ltr" {
  let r = 0, n = 0;
  for (const w of s.replace(QUIET, " ").split(/\s+/)) {
    const m = w.match(STRONG);
    if (m) { n++; if (RTL.test(m[0])) r++; }
  }
  return n && r * 3 >= n ? "rtl" : "ltr";
}

// A block in one script reads its own way; a mixed one takes its message's (undefined: inherit it).
export const blockDir = (s: string): "rtl" | "ltr" | undefined =>
  RTL.test(s) === LTR.test(s) ? undefined : RTL.test(s) ? "rtl" : "ltr";
