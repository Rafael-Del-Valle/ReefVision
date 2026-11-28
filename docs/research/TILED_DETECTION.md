# Rectangular detection tiles

In a project, register a trusted local Ultralytics detection checkpoint in **Model Hub**. Import the source images, select them in the **Gallery**, and open **Model inference** in the inspector.

1. Select the detector, confidence threshold and device.
2. Expand **Advanced inference settings** and select **Use rectangular tiles**.
3. For a 1920 × 1344 crop with 40% overlap, enter **1920**, **1344**, **40** and **40**. The percentage applies separately to width and height. The last window on each axis ends at the original edge. An image smaller than a tile uses its actual dimensions.
4. Set **Tiles per model batch** for available memory. A batch of one uses the least tile memory. Leave **Model input long side** empty for the crop dimensions with model-stride padding, or enter a long side to resize proportionally before prediction. This controls the model input, while annotation coordinates remain in the original raster.
5. **Per-tile IoU** controls the detector’s suppression within each crop. **Global merge IoU** controls suppression across the source image. The higher-confidence box wins when boxes of the same class overlap above that threshold. A partly visible object at a seam can yield boxes whose overlap falls below the threshold. Review seam and edge detections for your specimen sizes.
6. Choose **Run model on selected images**. Open the image in the annotation editor, correct and accept or reject each proposal. Freeze the reviewed dataset version and export its YOLO labels.

The job and proposals record the crop, overlap, batch, resize and suppression parameters. Whole-image detection remains the default. This option supports Ultralytics still-image bounding boxes. Segmentation, native ReefPose and video use their own inference workflows. An existing reviewed whole-image runtime selection retains its recorded settings.

The automated fixture places known objects inside an overlap and at the bottom-right source boundary. The real-checkpoint test uses locally generated weights on synthetic imagery. Researchers must evaluate recall, duplication and localization on independently annotated biological images before selecting a tiling policy.
