export interface SseMessage {
  id: number | null;
  data: string;
}

/**
 * An incremental Server-Sent Events parser.
 *
 * The browser's EventSource cannot send an Authorization header, so the UI reads the stream with
 * fetch and parses it here.
 */
export class SseParser {
  private buffer = "";

  feed(chunk: string): SseMessage[] {
    // Normalise the whole buffer: a CRLF can be split across two network chunks.
    this.buffer = (this.buffer + chunk).replaceAll("\r\n", "\n");
    const blocks = this.buffer.split("\n\n");
    this.buffer = blocks.pop() ?? "";
    return blocks.flatMap((block) => {
      const message = parseBlock(block);
      return message ? [message] : [];
    });
  }
}

function parseBlock(block: string): SseMessage | null {
  let id: number | null = null;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("id:")) {
      id = Number(line.slice(3).trim());
    } else if (line.startsWith("data:")) {
      data.push(line.slice(5).replace(/^ /, ""));
    }
  }
  return data.length > 0 ? { id, data: data.join("\n") } : null;
}
