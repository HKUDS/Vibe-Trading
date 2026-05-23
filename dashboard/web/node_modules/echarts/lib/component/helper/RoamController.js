
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


/**
 * AUTO-GENERATED FILE. DO NOT MODIFY.
 */

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
import { __extends } from "tslib";
import Eventful from 'zrender/lib/core/Eventful.js';
import * as eventTool from 'zrender/lib/core/event.js';
import * as interactionMutex from './interactionMutex.js';
import { isString, bind, defaults, extend, retrieve2 } from 'zrender/lib/core/util.js';
import { makeInner } from '../../util/model.js';
import { retrieveZInfo } from '../../util/graphic.js';
import { onIrrelevantElement } from './cursorHelper.js';
;
/**
 * An manager of zoom and pan(darg) hehavior.
 * But it is not responsible for updating the view, since view updates vary and can
 * not be handled in a uniform way.
 *
 * Note: regarding view updates:
 *  - Transformabe views typically use `coord/View` (e.g., geo and series.graph roaming).
 *    Some commonly used view update logic has been organized into `roamHelper.ts`.
 *  - Non-transformable views handle updates themselves, possibly involving re-layout,
 *    (e.g., treemap).
 *  - Some scenarios do not require transformation (e.g., dataZoom roaming for cartesian,
 *    brush component).
 */
var RoamController = /** @class */function (_super) {
  __extends(RoamController, _super);
  function RoamController(zr) {
    var _this = _super.call(this) || this;
    _this._zr = zr;
    // Avoid two roamController bind the same handler
    var mousedownHandler = bind(_this._mousedownHandler, _this);
    var mousemoveHandler = bind(_this._mousemoveHandler, _this);
    var mouseupHandler = bind(_this._mouseupHandler, _this);
    var mousewheelHandler = bind(_this._mousewheelHandler, _this);
    var pinchHandler = bind(_this._pinchHandler, _this);
    /**
     * Notice:
     *  - only enable needed types. For example, if 'zoom'
     *    is not needed, 'zoom' should not be enabled, otherwise
     *    default mousewheel behaviour (scroll page) will be disabled.
     *  - This method is idempotent.
     */
    _this.enable = function (controlType, rawOpt) {
      var zInfo = rawOpt.zInfo;
      var _a = retrieveZInfo(zInfo.component),
        z = _a.z,
        zlevel = _a.zlevel;
      var zInfoParsed = {
        component: zInfo.component,
        z: z,
        zlevel: zlevel,
        // By default roam controller is the lowest z2 comparing to other elememts in a component.
        z2: retrieve2(zInfo.z2, -Infinity)
      };
      var triggerInfo = extend({}, rawOpt.triggerInfo);
      this._opt = defaults(extend({}, rawOpt), {
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        // By default, wheel do not trigger move.
        moveOnMouseWheel: false,
        preventDefaultMouseMove: true,
        zInfoParsed: zInfoParsed,
        triggerInfo: triggerInfo,
        cursorGrab: 'grab',
        cursorGrabbing: 'grabbing'
      });
      if (controlType == null) {
        controlType = true;
      }
      // A quick optimization for repeatedly calling `enable` during roaming.
      // Assert `disable` is only affected by `controlType`.
      if (!this._enabled || this._controlType !== controlType) {
        // Disable previous first
        this.disable();
        this._enabled = true;
        if (controlType === true || controlType === 'move' || controlType === 'pan') {
          addRoamZrListener(zr, 'mousedown', mousedownHandler, zInfoParsed);
          addRoamZrListener(zr, 'mousemove', mousemoveHandler, zInfoParsed);
          addRoamZrListener(zr, 'mouseup', mouseupHandler, zInfoParsed);
        }
        if (controlType === true || controlType === 'scale' || controlType === 'zoom') {
          addRoamZrListener(zr, 'mousewheel', mousewheelHandler, zInfoParsed);
          addRoamZrListener(zr, 'pinch', pinchHandler, zInfoParsed);
        }
      }
    };
    _this.disable = function () {
      if (this._enabled) {
        this._enabled = false;
        removeRoamZrListener(zr, 'mousedown', mousedownHandler);
        removeRoamZrListener(zr, 'mousemove', mousemoveHandler);
        removeRoamZrListener(zr, 'mouseup', mouseupHandler);
        removeRoamZrListener(zr, 'mousewheel', mousewheelHandler);
        removeRoamZrListener(zr, 'pinch', pinchHandler);
      }
    };
    return _this;
  }
  RoamController.prototype.isDragging = function () {
    return this._dragging;
  };
  RoamController.prototype.isPinching = function () {
    return this._pinching;
  };
  RoamController.prototype._checkPointer = function (e, x, y) {
    var opt = this._opt;
    var zInfoParsed = opt.zInfoParsed;
    if (onIrrelevantElement(e, opt.api, zInfoParsed.component)) {
      return false;
    }
    ;
    var triggerInfo = opt.triggerInfo;
    var roamTrigger = triggerInfo.roamTrigger;
    var inArea = false;
    if (roamTrigger === 'global') {
      inArea = true;
    }
    if (!inArea) {
      inArea = triggerInfo.isInSelf(e, x, y);
    }
    if (inArea && triggerInfo.isInClip && !triggerInfo.isInClip(e, x, y)) {
      inArea = false;
    }
    return inArea;
  };
  RoamController.prototype._decideCursorStyle = function (e, x, y, forReverse) {
    // If this cursor style decision is not strictly consistent with zrender,
    // it's fine - zr will set the cursor on the next mousemove.
    // This `grab` cursor style should take the lowest precedence. If the hovring element already
    // have a cursor, zrender will set it to be non-'default' before entering this handler.
    // (note, e.target is never silent, e.topTarget can be silent be irrelevant.)
    var target = e.target;
    if (!target && this._checkPointer(e, x, y)) {
      // To indicate users that this area is draggable, otherwise users probably cannot kwown
      // that when hovering out of the shape but still inside the bounding rect.
      return this._opt.cursorGrab;
    }
    if (forReverse) {
      return target && target.cursor || 'default';
    }
  };
  RoamController.prototype.dispose = function () {
    this.disable();
  };
  RoamController.prototype._mousedownHandler = function (e) {
    if (eventTool.isMiddleOrRightButtonOnMouseUpDown(e) || eventConsumed(e)) {
      return;
    }
    var el = e.target;
    while (el) {
      if (el.draggable) {
        return;
      }
      // check if host is draggable
      el = el.__hostTarget || el.parent;
    }
    var x = e.offsetX;
    var y = e.offsetY;
    // To determine dragging start, only by checking on mosedown, but not mousemove.
    // Mouse can be out of target when mouse moving.
    if (this._checkPointer(e, x, y)) {
      this._x = x;
      this._y = y;
      this._dragging = true;
    }
  };
  RoamController.prototype._mousemoveHandler = function (e) {
    var zr = this._zr;
    if (e.gestureEvent === 'pinch' || interactionMutex.isTaken(zr, 'globalPan') || eventConsumed(e)) {
      return;
    }
    var x = e.offsetX;
    var y = e.offsetY;
    if (!this._dragging || !isAvailableBehavior('moveOnMouseMove', e, this._opt)) {
      var cursorStyle = this._decideCursorStyle(e, x, y, false);
      if (cursorStyle) {
        zr.setCursorStyle(cursorStyle);
      }
      return;
    }
    zr.setCursorStyle(this._opt.cursorGrabbing);
    var oldX = this._x;
    var oldY = this._y;
    var dx = x - oldX;
    var dy = y - oldY;
    this._x = x;
    this._y = y;
    if (this._opt.preventDefaultMouseMove) {
      eventTool.stop(e.event);
    }
    e.__ecRoamConsumed = true;
    trigger(this, 'pan', 'moveOnMouseMove', e, {
      dx: dx,
      dy: dy,
      oldX: oldX,
      oldY: oldY,
      newX: x,
      newY: y,
      isAvailableBehavior: null
    });
  };
  RoamController.prototype._mouseupHandler = function (e) {
    if (eventConsumed(e)) {
      return;
    }
    var zr = this._zr;
    if (!eventTool.isMiddleOrRightButtonOnMouseUpDown(e)) {
      this._dragging = false;
      var cursorStyle = this._decideCursorStyle(e, e.offsetX, e.offsetY, true);
      if (cursorStyle) {
        zr.setCursorStyle(cursorStyle);
      }
    }
  };
  RoamController.prototype._mousewheelHandler = function (e) {
    if (eventConsumed(e)) {
      return;
    }
    var shouldZoom = isAvailableBehavior('zoomOnMouseWheel', e, this._opt);
    var shouldMove = isAvailableBehavior('moveOnMouseWheel', e, this._opt);
    var wheelDelta = e.wheelDelta;
    var absWheelDeltaDelta = Math.abs(wheelDelta);
    var originX = e.offsetX;
    var originY = e.offsetY;
    // wheelDelta maybe -0 in chrome mac.
    if (wheelDelta === 0 || !shouldZoom && !shouldMove) {
      return;
    }
    // If both `shouldZoom` and `shouldMove` is true, trigger
    // their event both, and the final behavior is determined
    // by event listener themselves.
    if (shouldZoom) {
      // Convenience:
      // Mac and VM Windows on Mac: scroll up: zoom out.
      // Windows: scroll up: zoom in.
      // FIXME: Should do more test in different environment.
      // wheelDelta is too complicated in difference nvironment
      // (https://developer.mozilla.org/en-US/docs/Web/Events/mousewheel),
      // although it has been normallized by zrender.
      // wheelDelta of mouse wheel is bigger than touch pad.
      var factor = absWheelDeltaDelta > 3 ? 1.4 : absWheelDeltaDelta > 1 ? 1.2 : 1.1;
      var scale = wheelDelta > 0 ? factor : 1 / factor;
      this._checkTriggerMoveZoom(this, 'zoom', 'zoomOnMouseWheel', e, {
        scale: scale,
        originX: originX,
        originY: originY,
        isAvailableBehavior: null
      });
    }
    if (shouldMove) {
      // FIXME: Should do more test in different environment.
      var absDelta = Math.abs(wheelDelta);
      // wheelDelta of mouse wheel is bigger than touch pad.
      var scrollDelta = (wheelDelta > 0 ? 1 : -1) * (absDelta > 3 ? 0.4 : absDelta > 1 ? 0.15 : 0.05);
      this._checkTriggerMoveZoom(this, 'scrollMove', 'moveOnMouseWheel', e, {
        scrollDelta: scrollDelta,
        originX: originX,
        originY: originY,
        isAvailableBehavior: null
      });
    }
  };
  RoamController.prototype._pinchHandler = function (e) {
    if (interactionMutex.isTaken(this._zr, 'globalPan') || eventConsumed(e)) {
      return;
    }
    var scale = e.pinchScale > 1 ? 1.1 : 1 / 1.1;
    this._checkTriggerMoveZoom(this, 'zoom', null, e, {
      scale: scale,
      originX: e.pinchX,
      originY: e.pinchY,
      isAvailableBehavior: null
    });
  };
  RoamController.prototype._checkTriggerMoveZoom = function (controller, eventName, behaviorToCheck, e, contollerEvent) {
    if (controller._checkPointer(e, contollerEvent.originX, contollerEvent.originY)) {
      // When mouse is out of roamController rect,
      // default befavoius should not be be disabled, otherwise
      // page sliding is disabled, contrary to expectation.
      eventTool.stop(e.event);
      e.__ecRoamConsumed = true;
      trigger(controller, eventName, behaviorToCheck, e, contollerEvent);
    }
  };
  return RoamController;
}(Eventful);
function eventConsumed(e) {
  return e.__ecRoamConsumed;
}
var innerZrStore = makeInner();
function ensureZrStore(zr) {
  var store = innerZrStore(zr);
  store.roam = store.roam || {};
  store.uniform = store.uniform || {};
  return store;
}
/**
 * Listeners are sorted by z2/z/zlevel in descending order.
 * This decides the precedence between different roam controllers if they are overlapped.
 *
 * [MEMO]: It's not easy to perfectly reconcile the conflicts caused by overlap.
 *  - Consider cases:
 *    - Multiple roam controllers overlapped.
 *      - Usually only the topmost can trigger roam.
 *    - Roam controllers overlap with other zr elements:
 *      - zr elements are relevant or irrelevent to the host of the roam controller. e.g., axis split line
 *        or series elements is relevant to a cartesian and should trigger roam.
 *      - zr elements is above or below the roam controller host, which affects the precedence of interaction.
 *      - zr elements may not silent only for triggering tooltip by hovering, which is available to roam;
 *        or may not silent for click, where roam is not preferable.
 *  - Approach - `addRoamZrListener+pointerChecker+onIrrelevantElement` (currently used):
 *    - Resolve the precedence between different roam controllers
 *    - But cannot prevent the handling on other zr elements that under the roam controller in z-order.
 *  - Approach - "use an invisible zr elements to receive the zr events to trigger roam":
 *    - More complicated in impl.
 *    - May cause bad cases where zr event cannot be receive due to other non-silient zr elements covering it.
 */
function addRoamZrListener(zr, eventType, listener, zInfoParsed) {
  var store = ensureZrStore(zr);
  var roam = store.roam;
  var listenerList = roam[eventType] = roam[eventType] || [];
  var idx = 0;
  for (; idx < listenerList.length; idx++) {
    var currZInfo = listenerList[idx].zInfoParsed;
    if ((currZInfo.zlevel - zInfoParsed.zlevel || currZInfo.z - zInfoParsed.z || currZInfo.z2 - zInfoParsed.z2
    // If all equals, the latter added one has a higher precedence.
    ) <= 0) {
      break;
    }
  }
  listenerList.splice(idx, 0, {
    listener: listener,
    zInfoParsed: zInfoParsed
  });
  ensureUniformListener(zr, eventType);
}
function removeRoamZrListener(zr, eventType, listener) {
  var store = ensureZrStore(zr);
  var listenerList = store.roam[eventType] || [];
  for (var idx = 0; idx < listenerList.length; idx++) {
    if (listenerList[idx].listener === listener) {
      listenerList.splice(idx, 1);
      if (!listenerList.length) {
        removeUniformListener(zr, eventType);
      }
      return;
    }
  }
}
function ensureUniformListener(zr, eventType) {
  var store = ensureZrStore(zr);
  if (!store.uniform[eventType]) {
    zr.on(eventType, store.uniform[eventType] = function (event) {
      var listenerList = store.roam[eventType];
      if (listenerList) {
        for (var i = 0; i < listenerList.length; i++) {
          listenerList[i].listener(event);
        }
      }
    });
  }
}
function removeUniformListener(zr, eventType) {
  var store = ensureZrStore(zr);
  var uniform = store.uniform;
  if (uniform[eventType]) {
    zr.off(eventType, uniform[eventType]);
    uniform[eventType] = null;
  }
}
function trigger(controller, eventName, behaviorToCheck, e, contollerEvent) {
  // Also provide behavior checker for event listener, for some case that
  // multiple components share one listener.
  contollerEvent.isAvailableBehavior = bind(isAvailableBehavior, null, behaviorToCheck, e);
  // TODO should not have type issue.
  controller.trigger(eventName, contollerEvent);
}
// settings: {
//     zoomOnMouseWheel
//     moveOnMouseMove
//     moveOnMouseWheel
// }
// The value can be: true / false / 'shift' / 'ctrl' / 'alt'.
function isAvailableBehavior(behaviorToCheck, e, settings) {
  var setting = settings[behaviorToCheck];
  return !behaviorToCheck || setting && (!isString(setting) || e.event[setting + 'Key']);
}
export default RoamController;