import { describe, expect, it } from "vitest";
import { SseParser } from "./sse";

describe("SseParser", () => {
  it("parses a complete message", () => {
    const parser = new SseParser();

    expect(parser.feed('id: 3\ndata: {"a":1}\n\n')).toEqual([{ id: 3, data: '{"a":1}' }]);
  });

  it("buffers messages split across network chunks", () => {
    const parser = new SseParser();

    expect(parser.feed("id: 1\nda")).toEqual([]);
    expect(parser.feed('ta: {"a"')).toEqual([]);
    expect(parser.feed(":1}\n")).toEqual([]);
    expect(parser.feed("\n")).toEqual([{ id: 1, data: '{"a":1}' }]);
  });

  it("handles a CRLF split across two chunks", () => {
    const parser = new SseParser();

    expect(parser.feed("id: 1\r\ndata: a\r")).toEqual([]);
    expect(parser.feed("\n\r\n")).toEqual([{ id: 1, data: "a" }]);
  });

  it("ignores an id that is not a number", () => {
    const parser = new SseParser();

    expect(parser.feed("id: abc\ndata: a\n\n")).toEqual([{ id: null, data: "a" }]);
  });

  it("returns several messages from one chunk", () => {
    const parser = new SseParser();

    const messages = parser.feed("id: 1\ndata: a\n\nid: 2\ndata: b\n\n");

    expect(messages.map((message) => message.data)).toEqual(["a", "b"]);
  });

  it("ignores keepalive comments", () => {
    const parser = new SseParser();

    expect(parser.feed(": ping\n\n")).toEqual([]);
    expect(parser.feed(": ping\n\nid: 1\ndata: a\n\n")).toEqual([{ id: 1, data: "a" }]);
  });

  it("handles CRLF line endings", () => {
    const parser = new SseParser();

    expect(parser.feed("id: 1\r\ndata: a\r\n\r\n")).toEqual([{ id: 1, data: "a" }]);
  });

  it("joins multi-line data", () => {
    const parser = new SseParser();

    expect(parser.feed("data: a\ndata: b\n\n")).toEqual([{ id: null, data: "a\nb" }]);
  });
});
