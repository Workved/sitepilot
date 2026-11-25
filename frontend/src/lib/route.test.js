import { beforeEach, describe, expect, it } from "vitest";
import { readRoute, stripAuthParams } from "./route";

describe("stripAuthParams", () => {
  beforeEach(() => window.history.replaceState({}, "", "/"));

  it("drops one-time sign-in parameters but keeps the workspace route", () => {
    window.history.replaceState({}, "", "/?tab=broadcasts&broadcast=b1&code=abc&state=x#access_token=t");
    stripAuthParams();
    expect(window.location.search).toBe("?tab=broadcasts&broadcast=b1");
    expect(window.location.hash).toBe("");
    expect(readRoute()).toMatchObject({ tab: "broadcasts", broadcast: "b1" });
  });

  it("leaves a clean URL alone", () => {
    window.history.replaceState({}, "", "/?tab=projects&project=PRJ-1&pane=team");
    stripAuthParams();
    expect(window.location.search).toBe("?tab=projects&project=PRJ-1&pane=team");
  });
});
