import { describe, expect, it } from "vitest";
import { clock, durationLabel, hostOf, minutes, prettyNumber, sourceLabel } from "../format";

describe("minutes", () => {
  it("reads as a cook would say it", () => {
    expect(minutes(45)).toBe("45 min");
    expect(minutes(60)).toBe("1 h");
    expect(minutes(95)).toBe("1 h 35 min");
    expect(minutes(null)).toBe("");
    expect(minutes(0)).toBe("");
  });
});

describe("clock", () => {
  it("counts down in minutes until an hour is involved", () => {
    expect(clock(59)).toBe("0:59");
    expect(clock(90)).toBe("1:30");
    expect(clock(3661)).toBe("1:01:01");
    expect(clock(-5)).toBe("0:00");
  });
});

describe("durationLabel", () => {
  it("names a timer in its largest whole unit", () => {
    expect(durationLabel(1800)).toBe("30 min");
    expect(durationLabel(3600)).toBe("1 h");
    expect(durationLabel(45)).toBe("45s");
  });
});

describe("prettyNumber", () => {
  it("writes fractions the way a recipe does", () => {
    expect(prettyNumber(1)).toBe("1");
    expect(prettyNumber(1.5)).toBe("1½");
    expect(prettyNumber(0.25)).toBe("¼");
    expect(prettyNumber(0.75)).toBe("¾");
    expect(prettyNumber(null)).toBe("");
  });

  it("falls back to a decimal when no fraction is close", () => {
    expect(prettyNumber(1.07)).toBe("1.07");
  });
});

describe("hostOf", () => {
  it("strips the scheme and www", () => {
    expect(hostOf("https://www.smittenkitchen.com/soup")).toBe("smittenkitchen.com");
    expect(hostOf(null)).toBe("");
    expect(hostOf("not a url")).toBe("not a url");
  });
});

describe("sourceLabel", () => {
  it("names each capture route", () => {
    expect(sourceLabel("instagram")).toBe("Instagram");
    expect(sourceLabel("video_file")).toBe("Video file");
    expect(sourceLabel(null)).toBe("");
  });
});
