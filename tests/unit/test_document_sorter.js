/* Unit test for js/documents/document-sorter.js — synthetic names only
   (no real passport data). Run: node tests/unit/test_document_sorter.js */
"use strict";
const assert = require("assert");
const S = require("../../js/documents/document-sorter.js");

let passed = 0;
function check(name, fn) {
  try { fn(); passed++; console.log("[PASS] " + name); }
  catch (e) { console.log("[FAIL] " + name + "\n   " + e.message); process.exitCode = 1; }
}
const pp = (id, surname, givenNames) => ({ id, surname, givenNames, fileName: id + ".jpg" });
const v = (id, ...guestNames) => ({ id, guestNames, fileName: id + ".pdf" });
const roleOf = (r, id) => r.passports.find((x) => x.id === id);
const vOf = (r, id) => r.vouchers.find((x) => x.id === id);

check("tokens drop honorifics, accents and punctuation", () => {
  assert.deepStrictEqual(S.nameTokens("Mr. José-Luis  O'Neil"), ["JOSE", "LUIS", "O", "NEIL"]);
});
check("order-independent full match is high", () => {
  assert.ok(S.nameMatchScore("Sharma Test Person", "TEST PERSON SHARMA") >= 0.85);
});
check("middle name left out still high", () => {
  assert.ok(S.nameMatchScore("Test Sharma", "TEST KUMAR SHARMA") >= 0.85);
});
check("different given name is not a match", () => {
  assert.ok(S.nameMatchScore("Test Sharma", "OTHER SHARMA") < 0.6);
});
check("single word is capped below high", () => {
  assert.ok(S.nameMatchScore("Test", "TEST KUMAR SHARMA") < 0.85);
});
check("initial alone never matches", () => {
  assert.strictEqual(S.nameMatchScore("T S", "TEST SHARMA"), 0);
});
check("one-letter OCR slip is tolerated on long names", () => {
  assert.ok(S.nameMatchScore("Test Sharma", "TEST SHARNA") >= 0.6);
});
check("empty input scores 0", () => {
  assert.strictEqual(S.nameMatchScore("", "A B"), 0);
  assert.strictEqual(S.nameMatchScore("A B", ""), 0);
});

check("main applicant found among several passports", () => {
  const r = S.sort("Test Sharma", [pp("p1", "VERMA", "ALPHA"), pp("p2", "SHARMA", "TEST KUMAR"), pp("p3", "ROY", "BETA")], []);
  assert.strictEqual(r.mainPassportId, "p2");
  assert.strictEqual(roleOf(r, "p2").role, "main");
  assert.strictEqual(roleOf(r, "p1").role, "unmatched");
  assert.strictEqual(roleOf(r, "p1").include, false);
});
check("same-surname passport becomes a companion (flagged medium)", () => {
  const r = S.sort("Test Sharma", [pp("p1", "SHARMA", "TEST"), pp("p2", "SHARMA", "SAMPLE")], []);
  assert.strictEqual(roleOf(r, "p2").role, "companion");
  assert.strictEqual(roleOf(r, "p2").confidence, "medium");
  assert.strictEqual(roleOf(r, "p2").include, true);
});
check("different-surname passport on the same voucher becomes a companion", () => {
  const r = S.sort("Test Sharma", [pp("p1", "SHARMA", "TEST"), pp("p2", "GUPTA", "SAMPLE")],
    [v("v1", "Test Sharma", "Sample Gupta")]);
  assert.strictEqual(roleOf(r, "p2").role, "companion");
  assert.strictEqual(roleOf(r, "p2").include, true);
});
check("different surname and no shared voucher stays unmatched", () => {
  const r = S.sort("Test Sharma", [pp("p1", "SHARMA", "TEST"), pp("p2", "GUPTA", "SAMPLE")], [v("v1", "Test Sharma")]);
  assert.strictEqual(roleOf(r, "p2").role, "unmatched");
});
check("voucher naming a group member is included, other voucher is not", () => {
  const r = S.sort("Test Sharma", [pp("p1", "SHARMA", "TEST KUMAR")], [v("v1", "Mr Test Kumar Sharma"), v("v2", "Zed Unrelated")]);
  assert.strictEqual(vOf(r, "v1").include, true);
  assert.strictEqual(vOf(r, "v1").matchedPassportId, "p1");
  assert.strictEqual(vOf(r, "v2").include, false);
});
check("voucher with no readable guest is left unticked with a reason", () => {
  const r = S.sort("Test Sharma", [pp("p1", "SHARMA", "TEST")], [v("v1")]);
  assert.strictEqual(vOf(r, "v1").include, false);
  assert.ok(/No guest name/.test(vOf(r, "v1").reason));
});
check("voucher matches typed name when the passport was unreadable", () => {
  const r = S.sort("Test Sharma", [{ id: "p1", fileName: "x.jpg" }], [v("v1", "Test Sharma")]);
  assert.strictEqual(roleOf(r, "p1").role, "unreadable");
  assert.strictEqual(r.mainPassportId, null);
  assert.strictEqual(vOf(r, "v1").include, true);
});
check("no main passport found: nothing is auto-included", () => {
  const r = S.sort("Nobody Here", [pp("p1", "SHARMA", "TEST")], []);
  assert.strictEqual(r.mainPassportId, null);
  assert.strictEqual(roleOf(r, "p1").include, false);
});
check("two travellers on two different applicants' groups do not mix", () => {
  const passports = [pp("a1", "SHARMA", "TEST"), pp("b1", "GUPTA", "SAMPLE")];
  const vouchers = [v("va", "Test Sharma"), v("vb", "Sample Gupta")];
  const r = S.sort("Sample Gupta", passports, vouchers);
  assert.strictEqual(r.mainPassportId, "b1");
  assert.strictEqual(vOf(r, "vb").include, true);
  assert.strictEqual(vOf(r, "va").include, false);
});

check("a name run together on one document and split on the other still matches (both ways)", () => {
  assert.ok(S.nameMatchScore("Rajesh Kumar Sharma", "SHARMA RAJESHKUMAR") >= 0.85);
  assert.ok(S.nameMatchScore("RajeshKumar Sharma", "SHARMA RAJESH KUMAR") >= 0.85);
  assert.ok(S.nameMatchScore("Anita Devi Rao", "RAO ANITADEVI") >= 0.85);
  assert.ok(S.nameMatchScore("Manmohan Singh Negi", "NEGI MAN MOHAN SINGH") >= 0.85);
  assert.ok(S.nameMatchScore("Raj Kumar", "RAJKUMAR") >= 0.85);
});
check("joining names never makes different people match", () => {
  assert.ok(S.nameMatchScore("Ravi Kumar", "KUMAR RAVINDER") < 0.6);
  assert.ok(S.nameMatchScore("Anil Sharma", "SHARMA SUNIL") < 0.6);
});
check("same consonants, different vowels is a medium match to verify, never high", () => {
  const s = S.nameMatchScore("Sunita Patil", "PATIL SUNEETA");
  assert.ok(s >= 0.6 && s < 0.85, String(s));
});
check("same-consonant first names alone, with a different surname, do not match", () => {
  assert.ok(S.nameMatchScore("Sunita Patil", "SHAH SUNEETA") < 0.6);
});

console.log(passed + " passed");
