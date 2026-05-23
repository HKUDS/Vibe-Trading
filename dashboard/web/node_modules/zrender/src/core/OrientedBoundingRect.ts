/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/

import Point, { PointLike } from './Point';
import BoundingRect, { BoundingRectIntersectOpt, createIntersectContext } from './BoundingRect';
import { MatrixArray } from './matrix';

const mathMin = Math.min;
const mathMax = Math.max;
const mathAbs = Math.abs;

const _extent = [0, 0];
const _extent2 = [0, 0];

const _intersectCtx = createIntersectContext();
const _minTv = _intersectCtx.minTv;
const _maxTv = _intersectCtx.maxTv;


class OrientedBoundingRect {

    // lt, rt, rb, lb
    private _corners: Point[] = [];

    private _axes: Point[] = [];

    private _origin: number[] = [0, 0];

    constructor(rect?: BoundingRect, transform?: MatrixArray) {
        for (let i = 0; i < 4; i++) {
            this._corners[i] = new Point();
        }
        for (let i = 0; i < 2; i++) {
            this._axes[i] = new Point();
        }

        if (rect) {
            this.fromBoundingRect(rect, transform);
        }
    }

    fromBoundingRect(rect: BoundingRect, transform?: MatrixArray) {
        const corners = this._corners;
        const axes = this._axes;
        const x = rect.x;
        const y = rect.y;
        const x2 = x + rect.width;
        const y2 = y + rect.height;
        corners[0].set(x, y);
        corners[1].set(x2, y);
        corners[2].set(x2, y2);
        corners[3].set(x, y2);

        if (transform) {
            for (let i = 0; i < 4; i++) {
                corners[i].transform(transform);
            }
        }

        // Calculate axes
        Point.sub(axes[0], corners[1], corners[0]);
        Point.sub(axes[1], corners[3], corners[0]);
        axes[0].normalize();
        axes[1].normalize();

        // Calculate projected origin
        for (let i = 0; i < 2; i++) {
            this._origin[i] = axes[i].dot(corners[0]);
        }
    }

    /**
     * If intersect with another OBB.
     *
     * [NOTICE]
     *  Touching the edge is considered an intersection.
     *  zero-width/height can still cause intersection if `touchThreshold` is 0.
     *  See more in `BoundingRectIntersectOpt['touchThreshold']`
     *
     * @param other Bounding rect to be intersected with
     * @param mtv
     *  If it's not overlapped. it means needs to move `other` rect with Maximum Translation Vector to be overlapped.
     *      FIXME: Maximum Translation Vector is buggy. Fix it before using it. See case in `test/obb-collide.html`.
     *  Else it means needs to move `other` rect with Minimum Translation Vector to be not overlapped.
     */
    intersect(
        other: OrientedBoundingRect,
        mtv?: PointLike,
        opt?: BoundingRectIntersectOpt
    ): boolean {
        // OBB collision with SAT method

        let overlapped = true;
        const noMtv = !mtv;

        if (mtv) {
            Point.set(mtv, 0, 0);
        }

        _intersectCtx.reset(opt, !noMtv);

        // Check two axes for both two obb.
        if (!this._intersectCheckOneSide(this, other, noMtv, 1)) {
            overlapped = false;
            if (noMtv) {
                // Early return if no need to calculate mtv
                return overlapped;
            }
        }
        if (!this._intersectCheckOneSide(other, this, noMtv, -1)) {
            overlapped = false;
            if (noMtv) {
                return overlapped;
            }
        }

        if (!noMtv && !_intersectCtx.negativeSize) {
            Point.copy(
                mtv,
                overlapped
                    ? (_intersectCtx.useDir ? _intersectCtx.dirMinTv : _minTv)
                    : _maxTv
            );
        }

        return overlapped;
    }


    private _intersectCheckOneSide(
        self: OrientedBoundingRect,
        other: OrientedBoundingRect,
        noMtv: boolean,
        inverse: 1 | -1,
    ): boolean {

        // [CAVEAT] Must not use `this` in this method.

        let overlapped = true;
        for (let i = 0; i < 2; i++) {
            const axis = self._axes[i];
            self._getProjMinMaxOnAxis(i, self._corners, _extent);
            self._getProjMinMaxOnAxis(i, other._corners, _extent2);

            // Following the behavior in `BoundingRect.ts`, touching the edge is considered
            //  an overlap, but get a mtv [0, 0].
            if (_intersectCtx.negativeSize || _extent[1] < _extent2[0] || _extent[0] > _extent2[1]) {
                // Not overlap on the any axis.
                overlapped = false;
                if (_intersectCtx.negativeSize || noMtv) {
                    return overlapped;
                }
                const dist0 = mathAbs(_extent2[0] - _extent[1]);
                const dist1 = mathAbs(_extent[0] - _extent2[1]);

                // Find longest distance of all axes.
                if (mathMin(dist0, dist1) > _maxTv.len()) {
                    if (dist0 < dist1) {
                        Point.scale(_maxTv, axis, -dist0 * inverse);
                    }
                    else {
                        Point.scale(_maxTv, axis, dist1 * inverse);
                    }
                }
            }
            else if (!noMtv) {
                const dist0 = mathAbs(_extent2[0] - _extent[1]);
                const dist1 = mathAbs(_extent[0] - _extent2[1]);

                if (_intersectCtx.useDir || mathMin(dist0, dist1) < _minTv.len()) {
                    // If bidirectional, both dist0 dist1 need to check,
                    // otherwise only check the smaller one.
                    if (dist0 < dist1 || !_intersectCtx.bidirectional) {
                        Point.scale(_minTv, axis, dist0 * inverse);
                        if (_intersectCtx.useDir) {
                            _intersectCtx.calcDirMTV();
                        }
                    }
                    if (dist0 >= dist1 || !_intersectCtx.bidirectional) {
                        Point.scale(_minTv, axis, -dist1 * inverse);
                        if (_intersectCtx.useDir) {
                            _intersectCtx.calcDirMTV();
                        }
                    }
                }
            }
        }
        return overlapped;
    }

    private _getProjMinMaxOnAxis(dim: number, corners: Point[], out: number[]): void {
        const axis = this._axes[dim];
        const origin = this._origin;
        const proj = corners[0].dot(axis) + origin[dim];
        let min = proj;
        let max = proj;

        for (let i = 1; i < corners.length; i++) {
            const proj = corners[i].dot(axis) + origin[dim];
            min = mathMin(proj, min);
            max = mathMax(proj, max);
        }

        out[0] = min + _intersectCtx.touchThreshold;
        out[1] = max - _intersectCtx.touchThreshold;

        _intersectCtx.negativeSize = out[1] < out[0];
    }
}

export default OrientedBoundingRect;
