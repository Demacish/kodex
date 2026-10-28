// zlib.crc32 (Node 22.2+) has no type in older @types/node.
import * as nodeZlib from "node:zlib";

export const zlib = nodeZlib as typeof nodeZlib & { crc32(data: Buffer): number };
