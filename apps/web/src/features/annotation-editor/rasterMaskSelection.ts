export interface RasterMaskSelectionItem {
  id: string;
}

export function resolveRasterMaskSelection(
  selectedMaskId: string | null,
  masks: RasterMaskSelectionItem[],
  createAnotherMaskRequested: boolean,
): string | null {
  if (createAnotherMaskRequested) {
    return null;
  }
  if (
    selectedMaskId !== null &&
    masks.some((mask) => mask.id === selectedMaskId)
  ) {
    return selectedMaskId;
  }
  return masks[0]?.id ?? null;
}
