/**
 * @obsolete
 * PENDING:
 *  - This file is not used anywhere currently.
 *  - This is a similar behavior to `dataZoom`, but historically supported separately.
 *    Can it be merged into `dataZoom`?
 *  - The impl need to be fixed, @see #15050 , and,
 *      - Remove side-effect.
 *      - Need to fix the case:
 *          series_a =>
 *              x_m (category): dataExtent: [3,8]
 *              y_i:
 *          series_b =>
 *              x_m (category): dataExtent: [4,6]
 *              y_j:
 *          series_c =>
 *              x_m (category): dataExtent: [5,7]
 *              y_j:
 *          dataZoom control y_i, so series_a is excluded.
 *          So x_m.condExtent = [4,6] U [5,7] = [4,7] , and use it to call ensureScaleRawExtentInfo.
 *              (incorrect?, supposed to be [3,8]?)
 *
 * See test case `test/axis-filter-extent.html`.
 *
 * The responsibility of this processor:
 *  Enable category axis to use the specified `min`/`max` to shrink the extent of the orthogonal axis in
 *  Cartesian2D. That is, if some data item on a category axis is out of the range of `min`/`max`, the
 *  extent of the orthogonal axis will exclude the data items.
 *  A typical case is bar-racing, where bars are sorted dynamically and may only need to
 *  displayed part of the whole bars.
 *
 * IMPL_MEMO:
 *  - For each triple xAxis-yAxis-series, if either xAxis or yAxis is controlled by a dataZoom,
 *    the triple should be ignored in this processor.
 *  - Input:
 *    - Cartesian series data ("series approximate extent" has been prepared).
 *    - Axis original `ScaleRawExtentInfo`
 *      (the content comes from ec option and "series approximate extent").
 *  - Modify(result):
 *    - `ScaleRawExtentInfo#min/max` of the determined "target axis".
 *    - "series approximate extent".
 */
