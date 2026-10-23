import { describe, expect, it } from "vitest";
import { metricText, roleLabel } from "./format";

describe("metric text", () => {
  it("distinguishes zero, missing data, and an undefined rate", () => {
    expect(metricText({ value: 0, value_state: "known" })).toBe("0");
    expect(metricText({ value: null, value_state: "missing" })).toBe("No data");
    expect(metricText({ value: null, value_state: "zero_denominator" })).toBe("Undefined");
  });

  it("renders role names for operators", () => {
    expect(roleLabel("campaign_manager")).toBe("campaign manager");
  });
});
