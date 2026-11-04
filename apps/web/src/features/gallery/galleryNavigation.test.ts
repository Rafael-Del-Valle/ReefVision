import { afterEach, describe, expect, it, vi } from "vitest";

import {
  parseGalleryPageDraft,
  readBrowserGalleryPreference,
  readGalleryPreference,
  resolveGalleryNavigation,
  writeGalleryPreference,
  writeBrowserGalleryPreference,
} from "./galleryNavigation";

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
}

describe("browser gallery storage access", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("recovers when WebView2 denies access to the localStorage property itself", () => {
    vi.stubGlobal("window", {
      get localStorage(): Storage {
        throw new DOMException("Access denied", "SecurityError");
      },
    });

    expect(readBrowserGalleryPreference("project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
    expect(() =>
      writeBrowserGalleryPreference("project-a", {
        imageId: "camera-original-1",
        page: 1,
        wrap: false,
      }),
    ).not.toThrow();
  });
});

describe("gallery preferences", () => {
  it("persists the recent image and page per project", () => {
    const storage = memoryStorage();

    writeGalleryPreference(storage, "project-a", {
      imageId: "image-49",
      page: 3,
      wrap: true,
    });

    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "image-49",
      page: 3,
      wrap: true,
    });
    expect(readGalleryPreference(storage, "project-b")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
  });

  it("restores a saved camera image from preferences written before wrap existed", () => {
    const storage = memoryStorage({
      "reefvision.gallery.project-a.v1": JSON.stringify({
        imageId: "camera-original-1",
        page: 4,
      }),
    });
    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "camera-original-1",
      page: 4,
      wrap: false,
    });
  });

  it("rejects malformed legacy image identifiers and wrapping flags", () => {
    for (const preference of [
      { page: 2, wrap: false },
      { imageId: 7, page: 2, wrap: false },
      { imageId: "camera-original-1", page: 2, wrap: "false" },
      { imageId: "camera-original-1", page: 2, wrap: null },
    ]) {
      const storage = memoryStorage({
        "reefvision.gallery.project-a.v1": JSON.stringify(preference),
      });
      expect(readGalleryPreference(storage, "project-a")).toEqual({
        imageId: null,
        page: 1,
        wrap: false,
      });
    }
  });

  it("rejects unsafe saved pages before loading the first camera image", () => {
    for (const page of [2 ** 53, 1e100, Number.MAX_VALUE]) {
      const storage = memoryStorage({
        "reefvision.gallery.project-a.v1": JSON.stringify({
          imageId: "image-12",
          page,
          wrap: true,
        }),
      });

      expect(readGalleryPreference(storage, "project-a")).toEqual({
        imageId: null,
        page: 1,
        wrap: false,
      });
    }
  });

  it("does not overwrite the last valid image with invalid asynchronous pagination", () => {
    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-original-1",
      page: 2,
      wrap: false,
    });
    const key = "reefvision.gallery.project-a.v1";
    const saved = storage.getItem(key);

    for (const page of [
      0,
      -1,
      1.5,
      Number.NaN,
      Number.POSITIVE_INFINITY,
      2 ** 53,
    ]) {
      writeGalleryPreference(storage, "project-a", {
        imageId: "stale-image",
        page,
        wrap: true,
      });
      expect(storage.getItem(key)).toBe(saved);
    }
    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: "camera-original-1",
      page: 2,
      wrap: false,
    });
  });

  it("rejects blank image IDs without hiding the initial viewport", () => {
    for (const imageId of ["", "   "]) {
      const storage = memoryStorage({
        "reefvision.gallery.project-a.v1": JSON.stringify({
          imageId,
          page: 7,
          wrap: true,
        }),
      });
      expect(readGalleryPreference(storage, "project-a")).toEqual({
        imageId: null,
        page: 1,
        wrap: false,
      });
    }

    const storage = memoryStorage();
    writeGalleryPreference(storage, "project-a", {
      imageId: "camera-original-1",
      page: 2,
      wrap: false,
    });
    const saved = storage.getItem("reefvision.gallery.project-a.v1");
    writeGalleryPreference(storage, "project-a", {
      imageId: " ",
      page: 99,
      wrap: true,
    });
    expect(storage.getItem("reefvision.gallery.project-a.v1")).toBe(saved);
  });

  it("keeps gallery navigation usable when WebView2 storage reads are denied", () => {
    const deniedStorage = {
      getItem: (_key: string): string | null => {
        throw new DOMException("Access denied", "SecurityError");
      },
    };
    expect(readGalleryPreference(deniedStorage, "project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
  });

  it("does not interrupt image selection when WebView2 storage writes are denied", () => {
    const deniedStorage = {
      setItem: (_key: string, _value: string): void => {
        throw new DOMException("Quota exceeded", "QuotaExceededError");
      },
    };
    expect(() =>
      writeGalleryPreference(deniedStorage, "project-a", {
        imageId: "camera-original-1",
        page: 1,
        wrap: false,
      }),
    ).not.toThrow();
  });

  it("falls back safely when stored data is corrupt", () => {
    const storage = memoryStorage({
      "reefvision.gallery.project-a.v1": '{"imageId":7,"page":-3}',
    });

    expect(readGalleryPreference(storage, "project-a")).toEqual({
      imageId: null,
      page: 1,
      wrap: false,
    });
  });
});

describe("parseGalleryPageDraft", () => {
  it("accepts exact decimal page numbers and clamps valid pages to the collection", () => {
    expect(parseGalleryPageDraft("2", 5)).toBe(2);
    expect(parseGalleryPageDraft(" 003 ", 5)).toBe(3);
    expect(parseGalleryPageDraft("999", 5)).toBe(5);
  });

  it("rejects exponent, fractional, partial, and unsafe page input", () => {
    for (const draft of [
      "",
      " ",
      "0",
      "-1",
      "1e3",
      "3.5",
      "3junk",
      "1_000",
      "9007199254740992",
    ]) {
      expect(parseGalleryPageDraft(draft, 5)).toBeNull();
    }
    expect(parseGalleryPageDraft("2", 0)).toBeNull();
    expect(parseGalleryPageDraft("2", Number.MAX_SAFE_INTEGER + 1)).toBeNull();
  });
});

describe("resolveGalleryNavigation", () => {
  it("does not navigate using stale or malformed pagination state", () => {
    const valid = {
      action: "next" as const,
      index: 2,
      itemCount: 3,
      page: 1,
      pages: 2,
      wrap: true,
    };
    for (const index of [-1, 3, Number.NaN, Number.POSITIVE_INFINITY, 1.5]) {
      expect(resolveGalleryNavigation({ ...valid, index })).toBeNull();
    }
    for (const page of [0, 3, Number.NaN, 1.5]) {
      expect(resolveGalleryNavigation({ ...valid, page })).toBeNull();
    }
    for (const pages of [0, Number.POSITIVE_INFINITY, 1.5]) {
      expect(resolveGalleryNavigation({ ...valid, pages })).toBeNull();
    }
    for (const itemCount of [0, Number.NaN, 1.5]) {
      expect(resolveGalleryNavigation({ ...valid, itemCount })).toBeNull();
    }
  });

  it("rejects malformed runtime navigation payloads instead of advancing an image", () => {
    const valid = {
      action: "next" as const,
      index: 0,
      itemCount: 2,
      page: 1,
      pages: 2,
      wrap: false,
    };
    expect(resolveGalleryNavigation({ ...valid, wrap: "false" as unknown as boolean })).toBeNull();
    expect(resolveGalleryNavigation({ ...valid, wrap: null as unknown as boolean })).toBeNull();
    expect(
      resolveGalleryNavigation({
        ...valid,
        action: "delete" as unknown as typeof valid.action,
      }),
    ).toBeNull();
  });

  it("moves within a page without requesting another page", () => {
    expect(
      resolveGalleryNavigation({
        action: "next",
        index: 3,
        itemCount: 24,
        page: 9,
        pages: 100_000,
        wrap: false,
      }),
    ).toEqual({ page: 9, edge: "index", index: 4 });
  });

  it("crosses page boundaries without loading the full collection", () => {
    expect(
      resolveGalleryNavigation({
        action: "next",
        index: 23,
        itemCount: 24,
        page: 9,
        pages: 100_000,
        wrap: false,
      }),
    ).toEqual({ page: 10, edge: "first" });
    expect(
      resolveGalleryNavigation({
        action: "previous",
        index: 0,
        itemCount: 24,
        page: 9,
        pages: 100_000,
        wrap: false,
      }),
    ).toEqual({ page: 8, edge: "last" });
  });

  it("supports first, last, optional wrapping, and single-image no-ops", () => {
    expect(
      resolveGalleryNavigation({
        action: "first",
        index: 4,
        itemCount: 24,
        page: 9,
        pages: 10,
        wrap: false,
      }),
    ).toEqual({ page: 1, edge: "first" });
    expect(
      resolveGalleryNavigation({
        action: "last",
        index: 4,
        itemCount: 24,
        page: 9,
        pages: 10,
        wrap: false,
      }),
    ).toEqual({ page: 10, edge: "last" });
    expect(
      resolveGalleryNavigation({
        action: "previous",
        index: 0,
        itemCount: 24,
        page: 1,
        pages: 10,
        wrap: true,
      }),
    ).toEqual({ page: 10, edge: "last" });
    expect(
      resolveGalleryNavigation({
        action: "next",
        index: 0,
        itemCount: 1,
        page: 1,
        pages: 1,
        wrap: true,
      }),
    ).toBeNull();
  });
});
