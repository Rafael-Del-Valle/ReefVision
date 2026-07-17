import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PolygonMaskLayer } from "./PolygonMaskLayer";

describe("polygon first-node closure", () => {
  it("closes only after the first node is clicked", () => {
    const onCreate = vi.fn();
    render(
      <PolygonMaskLayer
        width={400}
        height={300}
        masks={[]}
        classColors={{ "class-1": "#2a9d8f" }}
        activeClassId="class-1"
        tool="polygon"
        selectedMaskIds={[]}
        onCreate={onCreate}
        onUpdate={vi.fn()}
        onSelectionChange={vi.fn()}
      />,
    );

    const layer = screen.getByTestId(
      "polygon-mask-layer",
    ) as unknown as SVGSVGElement;
    vi.spyOn(layer, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 400,
      bottom: 300,
      width: 400,
      height: 300,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(layer, { clientX: 10, clientY: 10 });
    fireEvent.pointerDown(layer, { clientX: 50, clientY: 10 });
    fireEvent.pointerDown(layer, { clientX: 50, clientY: 50 });

    expect(onCreate).not.toHaveBeenCalled();
    fireEvent.pointerDown(screen.getByTestId("polygon-draft-point-0"));

    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onCreate.mock.calls[0][0]).toMatchObject({
      geometry_kind: "polygon",
      points: [
        { x: 10, y: 10 },
        { x: 50, y: 10 },
        { x: 50, y: 50 },
      ],
    });
  });
});
