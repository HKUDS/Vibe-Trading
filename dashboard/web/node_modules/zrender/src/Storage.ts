import * as util from './core/util';
import Group, { GroupLike } from './graphic/Group';
import Element from './Element';

// Use timsort because in most case elements are partially sorted
// https://jsfiddle.net/pissang/jr4x7mdm/8/
import timsort from './core/timsort';
import Displayable from './graphic/Displayable';
import Path from './graphic/Path';
import { REDRAW_BIT } from './graphic/constants';
import { NullUndefined } from './core/types';

let invalidZErrorLogged = false;
function logInvalidZError() {
    if (invalidZErrorLogged) {
        return;
    }
    invalidZErrorLogged = true;
    console.warn('z / z2 / zlevel of displayable is invalid, which may cause unexpected errors');
}

function shapeCompareFunc(a: Displayable, b: Displayable) {
    if (a.zlevel === b.zlevel) {
        if (a.z === b.z) {
            return a.z2 - b.z2;
        }
        return a.z - b.z;
    }
    return a.zlevel - b.zlevel;
}

export default class Storage {

    private _roots: Element[] = []

    private _displayList: Displayable[] = []

    private _displayListLen = 0

    traverse<T>(
        cb: (this: T, el: Element) => void,
        context?: T
    ) {
        for (let i = 0; i < this._roots.length; i++) {
            this._roots[i].traverse(cb, context);
        }
    }

    /**
     * get a list of elements to be rendered
     *
     * @param {boolean} update whether to update elements before return
     * @param {DisplayParams} params options
     * @return {Displayable[]} a list of elements
     */
    getDisplayList(update?: boolean, includeIgnore?: boolean): Displayable[] {
        includeIgnore = includeIgnore || false;
        const displayList = this._displayList;
        // If displaylist is not created yet. Update force
        if (update || !displayList.length) {
            this.updateDisplayList(includeIgnore);
        }
        return displayList;
    }

    /**
     * 更新图形的绘制队列。
     * 每次绘制前都会调用，该方法会先深度优先遍历整个树，更新所有Group和Shape的变换并且把所有可见的Shape保存到数组中，
     * 最后根据绘制的优先级（zlevel > z > 插入顺序）排序得到绘制队列
     */
    updateDisplayList(includeIgnore?: boolean) {
        this._displayListLen = 0;

        const roots = this._roots;
        const displayList = this._displayList;
        for (let i = 0, len = roots.length; i < len; i++) {
            this._updateAndAddDisplayable(roots[i], null, includeIgnore);
        }

        displayList.length = this._displayListLen;

        // PENDING: Indicatively, it may cost over 10~20ms when list length is over 1e5.
        // See PENDING_SEPARATE_DISPLAY_LIST
        timsort(displayList, shapeCompareFunc);
    }

    private _updateAndAddDisplayable(
        el: Element,
        parentClipPaths: Path[] | NullUndefined,
        includeIgnore?: boolean
    ) {
        if (el.ignore && !includeIgnore) {
            return;
        }

        el.beforeUpdate();
        el.update();
        el.afterUpdate();

        const userSetClipPath = el.getClipPath();
        const parentHasClipPaths = parentClipPaths && parentClipPaths.length;
        let clipPathIdx = 0;
        let thisClipPaths = el.__clipPaths;

        if (!el.ignoreClip
            && (parentHasClipPaths || userSetClipPath)
        ) { // has clipPath in this pass
            if (!thisClipPaths) {
                thisClipPaths = el.__clipPaths = [];
            }
            if (parentHasClipPaths) {
                // PENDING: performance?
                for (let idx = 0; idx < parentClipPaths.length; idx++) {
                    thisClipPaths[clipPathIdx++] = parentClipPaths[idx];
                }
            }

            let currentClipPath = userSetClipPath;
            let parentClipPath = el;
            // Recursively add clip path
            while (currentClipPath) {
                // clipPath 的变换是基于使用这个 clipPath 的元素
                // TODO: parent should be group type.
                currentClipPath.parent = parentClipPath as Group;
                currentClipPath.updateTransform();

                thisClipPaths[clipPathIdx++] = currentClipPath;

                parentClipPath = currentClipPath;
                currentClipPath = currentClipPath.getClipPath();
            }
        }

        if (thisClipPaths) { // Remove other old clipPath in array.
            thisClipPaths.length = clipPathIdx;
        }

        // ZRText and Group and combining morphing Path may use children
        if ((el as GroupLike).childrenRef) {
            const children = (el as GroupLike).childrenRef();

            for (let i = 0; i < children.length; i++) {
                const child = children[i];

                // Force to mark as dirty if group is dirty
                if (el.__dirty) {
                    child.__dirty |= REDRAW_BIT;
                }

                this._updateAndAddDisplayable(child, thisClipPaths, includeIgnore);
            }

            // Mark group clean here
            el.__dirty = 0;

        }
        else {
            const disp = el as Displayable;

            // Avoid invalid z, z2, zlevel cause sorting error.
            if (isNaN(disp.z)) {
                logInvalidZError();
                disp.z = 0;
            }
            if (isNaN(disp.z2)) {
                logInvalidZError();
                disp.z2 = 0;
            }
            if (isNaN(disp.zlevel)) {
                logInvalidZError();
                disp.zlevel = 0;
            }

            this._displayList[this._displayListLen++] = disp;
        }

        // Add decal
        const decalEl = (el as Path).getDecalElement && (el as Path).getDecalElement();
        if (decalEl) {
            this._updateAndAddDisplayable(decalEl, thisClipPaths, includeIgnore);
        }

        // Add attached text element and guide line.
        const textGuide = el.getTextGuideLine();
        if (textGuide) {
            this._updateAndAddDisplayable(textGuide, thisClipPaths, includeIgnore);
        }

        const textEl = el.getTextContent();
        if (textEl) {
            this._updateAndAddDisplayable(textEl, thisClipPaths, includeIgnore);
        }
    }

    /**
     * 添加图形(Displayable)或者组(Group)到根节点
     */
    addRoot(el: Element) {
        if (el.__zr && el.__zr.storage === this) {
            return;
        }

        this._roots.push(el);
    }

    /**
     * 删除指定的图形(Displayable)或者组(Group)
     * @param el
     */
    delRoot(el: Element | Element[]) {

        if (el instanceof Array) {
            for (let i = 0, l = el.length; i < l; i++) {
                this.delRoot(el[i]);
            }
            return;
        }

        const idx = util.indexOf(this._roots, el);
        if (idx >= 0) {
            this._roots.splice(idx, 1);
        }
    }

    delAllRoots() {
        this._roots = [];
        this._displayList = [];
        this._displayListLen = 0;

        return;
    }

    getRoots() {
        return this._roots;
    }

    /**
     * 清空并且释放Storage
     */
    dispose() {
        this._displayList = null;
        this._roots = null;
    }

    displayableSortFunc = shapeCompareFunc
}