import * as matrix from './matrix';
import * as vector from './vector';
import Point, { PointLike } from './Point';
import { NullUndefined } from './types';

const mathMin = Math.min;
const mathMax = Math.max;
const mathAbs = Math.abs;

const XY = ['x', 'y'] as const;
const WH = ['width', 'height'] as const;

const lt = new Point();
const rb = new Point();
const lb = new Point();
const rt = new Point();

const _intersectCtx = createIntersectContext();
const _minTv = _intersectCtx.minTv;
const _maxTv = _intersectCtx.maxTv;
// [min, max]
const _lenMinMax = [0, 0];

class BoundingRect {

    x: number
    y: number
    width: number
    height: number

    constructor(x: number, y: number, width: number, height: number) {
        boundingRectSet(this, x, y, width, height);
    }

    static set<TTarget extends RectLike>(
        target: TTarget, x: number, y: number, width: number, height: number
    ): TTarget {
        if (width < 0) {
            x = x + width;
            width = -width;
        }
        if (height < 0) {
            y = y + height;
            height = -height;
        }

        target.x = x;
        target.y = y;
        target.width = width;
        target.height = height;

        return target;
    }

    union(other: BoundingRect) {
        const x = mathMin(other.x, this.x);
        const y = mathMin(other.y, this.y);

        // If x is -Infinity and width is Infinity (like in the case of
        // IncrementalDisplayable), x + width would be NaN
        if (isFinite(this.x) && isFinite(this.width)) {
            this.width = mathMax(
                other.x + other.width,
                this.x + this.width
            ) - x;
        }
        else {
            this.width = other.width;
        }

        if (isFinite(this.y) && isFinite(this.height)) {
            this.height = mathMax(
                other.y + other.height,
                this.y + this.height
            ) - y;
        }
        else {
            this.height = other.height;
        }

        this.x = x;
        this.y = y;
    }

    applyTransform(m: matrix.MatrixArray) {
        BoundingRect.applyTransform(this, this, m);
    }

    calculateTransform(b: RectLike): matrix.MatrixArray {
        return boundingRectCalculateTransform(matrix.create(), this, b);
    }

    /**
     * @see `static intersect`
     */
    intersect(
        b: RectLike,
        mtv?: PointLike,
        opt?: BoundingRectIntersectOpt
    ): boolean {
        return BoundingRect.intersect(this, b, mtv, opt);
    }

    /**
     * [NOTICE]
     *  Touching the edge is considered an intersection.
     *  zero-width/height can still cause intersection if `touchThreshold` is 0.
     *  See more in `BoundingRectIntersectOpt['touchThreshold']`
     *
     * @param mtv
     *  If it's not overlapped. it means needs to move `b` rect with Maximum Translation Vector to be overlapped.
     *  Else it means needs to move `b` rect with Minimum Translation Vector to be not overlapped.
     */
    static intersect(
        a: RectLike,
        b: RectLike,
        mtv?: PointLike,
        opt?: BoundingRectIntersectOpt
    ): boolean {
        if (mtv) {
            Point.set(mtv, 0, 0);
        }
        const outIntersectRect = opt && opt.outIntersectRect || null;
        const clamp = opt && opt.clamp;
        if (outIntersectRect) {
            outIntersectRect.x = outIntersectRect.y = outIntersectRect.width = outIntersectRect.height = NaN;
        }

        if (!a || !b) {
            return false;
        }

        // Normalize negative width/height.
        if (!(a instanceof BoundingRect)) {
            a = boundingRectSet(_tmpIntersectA, a.x, a.y, a.width, a.height);
        }
        if (!(b instanceof BoundingRect)) {
            b = boundingRectSet(_tmpIntersectB, b.x, b.y, b.width, b.height);
        }

        const useMTV = !!mtv;

        _intersectCtx.reset(opt, useMTV);

        const touchThreshold = _intersectCtx.touchThreshold;

        const ax0 = a.x + touchThreshold;
        const ax1 = a.x + a.width - touchThreshold;
        const ay0 = a.y + touchThreshold;
        const ay1 = a.y + a.height - touchThreshold;

        const bx0 = b.x + touchThreshold;
        const bx1 = b.x + b.width - touchThreshold;
        const by0 = b.y + touchThreshold;
        const by1 = b.y + b.height - touchThreshold;

        if (ax0 > ax1 || ay0 > ay1 || bx0 > bx1 || by0 > by1) {
            return false;
        }

        const overlap = !(ax1 < bx0 || bx1 < ax0 || ay1 < by0 || by1 < ay0);

        if (useMTV || outIntersectRect) {
            _lenMinMax[0] = Infinity;
            _lenMinMax[1] = 0;

            intersectOneDim(ax0, ax1, bx0, bx1, 0, useMTV, outIntersectRect, clamp);
            intersectOneDim(ay0, ay1, by0, by1, 1, useMTV, outIntersectRect, clamp);

            if (useMTV) {
                Point.copy(
                    mtv,
                    overlap
                        ? (_intersectCtx.useDir ? _intersectCtx.dirMinTv : _minTv)
                        : _maxTv
                );
            }
        }

        return overlap;
    }

    static contain(rect: RectLike, x: number, y: number): boolean {
        return x >= rect.x
            && x <= (rect.x + rect.width)
            && y >= rect.y
            && y <= (rect.y + rect.height);
    }

    contain(x: number, y: number): boolean {
        return BoundingRect.contain(this, x, y);
    }

    clone() {
        return new BoundingRect(this.x, this.y, this.width, this.height);
    }

    /**
     * Copy from another rect
     */
    copy(other: RectLike) {
        boundingRectCopy(this, other);
    }

    plain(): RectLike {
        return {
            x: this.x,
            y: this.y,
            width: this.width,
            height: this.height
        };
    }

    /**
     * If not having NaN or Infinity with attributes
     */
    isFinite(): boolean {
        return isFinite(this.x)
            && isFinite(this.y)
            && isFinite(this.width)
            && isFinite(this.height);
    }

    isZero(): boolean {
        return this.width === 0 || this.height === 0;
    }

    static create(rect?: RectLike | NullUndefined): BoundingRect {
        return new BoundingRect(
            rect ? rect.x : 0,
            rect ? rect.y : 0,
            rect ? rect.width : 0,
            rect ? rect.height : 0
        );
    }

    static copy<TTarget extends RectLike>(target: TTarget, source: RectLike): TTarget {
        target.x = source.x;
        target.y = source.y;
        target.width = source.width;
        target.height = source.height;

        return target;
    }

    static applyTransform(target: RectLike, source: RectLike, m: matrix.MatrixArray) {
        // In case usage like this
        // el.getBoundingRect().applyTransform(el.transform)
        // And element has no transform
        if (!m) {
            if (target !== source) {
                boundingRectCopy(target, source);
            }
            return;
        }
        // Fast path when there is no rotation in matrix.
        if (m[1] < 1e-5 && m[1] > -1e-5 && m[2] < 1e-5 && m[2] > -1e-5) {
            const sx = m[0];
            const sy = m[3];
            const tx = m[4];
            const ty = m[5];
            target.x = source.x * sx + tx;
            target.y = source.y * sy + ty;
            target.width = source.width * sx;
            target.height = source.height * sy;
            if (target.width < 0) {
                target.x += target.width;
                target.width = -target.width;
            }
            if (target.height < 0) {
                target.y += target.height;
                target.height = -target.height;
            }
            return;
        }

        // source and target can be same instance.
        lt.x = lb.x = source.x;
        lt.y = rt.y = source.y;
        rb.x = rt.x = source.x + source.width;
        rb.y = lb.y = source.y + source.height;

        lt.transform(m);
        rt.transform(m);
        rb.transform(m);
        lb.transform(m);

        target.x = mathMin(lt.x, rb.x, lb.x, rt.x);
        target.y = mathMin(lt.y, rb.y, lb.y, rt.y);
        const maxX = mathMax(lt.x, rb.x, lb.x, rt.x);
        const maxY = mathMax(lt.y, rb.y, lb.y, rt.y);
        target.width = maxX - target.x;
        target.height = maxY - target.y;
    }

    static calculateTransform(out: matrix.MatrixArray | NullUndefined, a: RectLike, b: RectLike): matrix.MatrixArray {
        const sx = b.width / a.width;
        const sy = b.height / a.height;

        out = matrix.identity(out || []);

        matrix.translate(out, out, vector.set(_tmpCalcTrans, -a.x, -a.y));
        matrix.scale(out, out, vector.set(_tmpCalcTrans, sx, sy));
        matrix.translate(out, out, vector.set(_tmpCalcTrans, b.x, b.y));

        return out;
    }

}

export const boundingRectCreate = BoundingRect.create;
export const boundingRectSet = BoundingRect.set;
export const boundingRectCopy = BoundingRect.copy;
export const boundingRectCalculateTransform = BoundingRect.calculateTransform;
export const boundingRectApplyTransform = BoundingRect.applyTransform;
export const boundingRectContain = BoundingRect.contain;

const _tmpIntersectA = new BoundingRect(0, 0, 0, 0);
const _tmpIntersectB = new BoundingRect(0, 0, 0, 0);
const _tmpCalcTrans: vector.VectorArray = [];


function intersectOneDim(
    a0: number, a1: number, b0: number, b1: number,
    updateDimIdx: number,
    useMTV: boolean,
    outIntersectRect: BoundingRectIntersectOpt['outIntersectRect'],
    clamp: BoundingRectIntersectOpt['clamp']
): void {
    const d0 = mathAbs(a1 - b0);
    const d1 = mathAbs(b1 - a0);
    const d01min = mathMin(d0, d1);
    const updateDim = XY[updateDimIdx];
    const zeroDim = XY[1 - updateDimIdx];
    const wh = WH[updateDimIdx];

    if (a1 < b0 || b1 < a0) { // No intersection on this dimension.
        if (d0 < d1) {
            if (useMTV) {
                _maxTv[updateDim] = -d0; // b is on the right/bottom(larger x/y)
            }
            if (clamp) {
                outIntersectRect[updateDim] = a1;
                outIntersectRect[wh] = 0;
            }
        }
        else {
            if (useMTV) {
                _maxTv[updateDim] = d1; // b is on the left/top(smaller x/y)
            }
            if (clamp) {
                outIntersectRect[updateDim] = a0;
                outIntersectRect[wh] = 0;
            }
        }
    }
    else { // Has intersection
        if (outIntersectRect) {
            outIntersectRect[updateDim] = mathMax(a0, b0);
            outIntersectRect[wh] = mathMin(a1, b1) - outIntersectRect[updateDim];
        }
        if (useMTV) {
            if (d01min < _lenMinMax[0] || _intersectCtx.useDir) {
                // If bidirectional, both dist0 dist1 need to check,
                // otherwise only check the smaller one.
                _lenMinMax[0] = mathMin(d01min, _lenMinMax[0]);
                if (d0 < d1 || !_intersectCtx.bidirectional) {
                    _minTv[updateDim] = d0; // b is on the right/bottom(larger x/y)
                    _minTv[zeroDim] = 0;
                    if (_intersectCtx.useDir) {
                        _intersectCtx.calcDirMTV();
                    }
                }
                if (d0 >= d1 || !_intersectCtx.bidirectional) {
                    _minTv[updateDim] = -d1; // b is on the left/top(smaller x/y)
                    _minTv[zeroDim] = 0;
                    if (_intersectCtx.useDir) {
                        _intersectCtx.calcDirMTV();
                    }
                }
            }
        }
    }
}


export type RectLike = {
    x: number
    y: number
    width: number
    height: number
}

export interface BoundingRectIntersectOpt {
    /**
     * If specified, when overlapping, the output `mtv` is still a minimal vector that can resolve the overlap.
     * However it is not Minimum Translation Vector, but a vector follow the direction.
     * Be a radian, representing a vector direction.
     * `direction=atan2(y, x)`, i.e., `direction=0` is vector(1,0), `direction=PI/4` is vector(1,1).
     */
    direction?: number
    /**
     * By default `true`. It means whether `BoundingRectIntersectOpt['direction']` is bidirectional. If `true`,
     * the returned mtv is the minimal among both `opt.direction` and `opt.direction + Math.PI`.
     */
    bidirectional?: boolean
    /**
     * Two rects that touch but are within the threshold do not be considered an intersection.
     * Scenarios:
     *  - Without a `touchThreshold`, zero-width/height can still cause intersection.
     *    In some scenarios, a rect with border styles still needs to display even if width/height is zero;
     *    but in some other scenarios, zero-width/height represents "nothing", such as in HTML
     *    BoundingClientRect, or when zrender.Group has all children `ignored: true`. In this case, we can use
     *    a non-negative `touchThreshold` to form a "minus width/height" and force it to never cause an
     *    intersection. And in this case, mtv will not be calculated.
     *  - Without a `touchThreshold`, touching the edge is considered an intersection.
     *  - Having a `touchThreshold`, elements can use the same rect instance to achieve compact layout while
     *    still passing through the overlap-hiding handler.
     *  - a positive near-zero number is commonly used in `touchThreshold` for aggressive overlap handling,
     *    such as:
     *    - Hide one element if overlapping.
     *    - Two elements are vertically touching at top/bottom edges, but are restricted to move along
     *      the horizontal direction to resolve overlap.
     */
    touchThreshold?: number

    /**
     * - If an intersection occur, set the intersection rect to it.
     * - Otherwise,
     *   - If `clamp: true`, `outIntersectRect` is set with a clamped rect that is on the edge or corner
     *     of the first rect input to `intersect` method.
     *   - Otherwise, set to all NaN (it will not pass `contain` and `intersect`).
     */
    outIntersectRect?: RectLike
    clamp?: boolean;
}

/**
 * [CAVEAT] Do not use it other than in `BoundingRect` and `OrientedBoundingRect`.
 */
export function createIntersectContext() {

    let _direction: BoundingRectIntersectOpt['direction'] = 0;
    const _dirCheckVec = new Point();
    const _dirTmp = new Point();

    const _ctx = {
        minTv: new Point(),
        maxTv: new Point(),
        useDir: false as boolean,
        dirMinTv: new Point(),
        touchThreshold: 0 as BoundingRectIntersectOpt['touchThreshold'],
        bidirectional: true as BoundingRectIntersectOpt['bidirectional'],

        negativeSize: false as boolean,

        reset(opt: BoundingRectIntersectOpt | NullUndefined, useMTV: boolean): void {
            _ctx.touchThreshold = 0;
            if (opt && opt.touchThreshold != null) {
                _ctx.touchThreshold = mathMax(0, opt.touchThreshold);
            }
            _ctx.negativeSize = false;

            if (!useMTV) {
                return;
            }

            _ctx.minTv.set(Infinity, Infinity);
            _ctx.maxTv.set(0, 0);
            _ctx.useDir = false;

            if (opt && opt.direction != null) {
                _ctx.useDir = true;
                _ctx.dirMinTv.copy(_ctx.minTv);
                _dirTmp.copy(_ctx.minTv);
                _direction = opt.direction;
                _ctx.bidirectional = opt.bidirectional == null || !!opt.bidirectional;
                if (!_ctx.bidirectional) {
                    _dirCheckVec.set(Math.cos(_direction), Math.sin(_direction));
                }
            }
        },

        calcDirMTV(): void {
            const minTv = _ctx.minTv;
            const dirMinTv = _ctx.dirMinTv;
            const squareMag = minTv.y * minTv.y + minTv.x * minTv.x;
            const dirSin = Math.sin(_direction);
            const dirCos = Math.cos(_direction);
            const dotProd = dirSin * minTv.y + dirCos * minTv.x;

            if (nearZero(dotProd)) {
                if (nearZero(minTv.x) && nearZero(minTv.y)) {
                    // The two OBBs touch at the edges.
                    dirMinTv.set(0, 0);
                }
                // Otherwise `minTv` is perpendicular to `this.direction`.
                return;
            }

            _dirTmp.x = squareMag * dirCos / dotProd;
            _dirTmp.y = squareMag * dirSin / dotProd;
            if (nearZero(_dirTmp.x) && nearZero(_dirTmp.y)) {
                // The result includes near-(0,0) regardless of `bidirectional`.
                dirMinTv.set(0, 0);
                return;
            }

            if ((
                    _ctx.bidirectional
                    || _dirCheckVec.dot(_dirTmp) > 0
                )
                && _dirTmp.len() < dirMinTv.len()
            ) {
                dirMinTv.copy(_dirTmp);
            }
        }
    };

    function nearZero(val: number): boolean {
        return mathAbs(val) < 1e-10; // Empirically OK for pixel-scale values.
    }

    return _ctx;
}


export default BoundingRect;
