
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
import ComponentView from '../../view/Component.js';
import BoundingRect from 'zrender/lib/core/BoundingRect.js';
import * as matrix from 'zrender/lib/core/matrix.js';
import RoamController from '../helper/RoamController.js';
import tokens from '../../visual/tokens.js';
import { createBoxLayoutReference, getBoxLayoutParams, getLayoutRect } from '../../util/layout.js';
import { expandOrShrinkRect, Rect, Group, traverseUpdateZ, retrieveZInfo } from '../../util/graphic.js';
import { applyTransform } from 'zrender/lib/core/vector.js';
import View, { VIEW_COORD_SYS_TRANS_RAW, viewCoordSysCopyTrans, viewCoordSysSetBoundingRect, viewCoordSysSetViewRect, viewCoordSysCopyOverallMatrix } from '../../coord/View.js';
import { bind, defaults, extend } from 'zrender/lib/core/util.js';
var ThumbnailView = /** @class */function (_super) {
  __extends(ThumbnailView, _super);
  function ThumbnailView() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = ThumbnailView.type;
    return _this;
  }
  ThumbnailView.prototype.render = function (thumbnailModel, ecModel, api) {
    this._api = api;
    this._model = thumbnailModel;
    if (!this._coordSys) {
      this._coordSys = new View();
    }
    if (!this._isEnabled()) {
      this._clear();
      return;
    }
    this._renderVersion = api.getECUpdateCycleVersion();
    var group = this.group;
    group.removeAll();
    var itemStyleModel = thumbnailModel.getModel('itemStyle');
    var itemStyle = itemStyleModel.getItemStyle();
    if (itemStyle.fill == null) {
      itemStyle.fill = ecModel.get('backgroundColor') || tokens.color.neutral00;
    }
    var refContainer = createBoxLayoutReference(thumbnailModel, api).refContainer;
    var boxRect = getLayoutRect(getBoxLayoutParams(thumbnailModel, true), refContainer);
    var boxBorderWidth = itemStyle.lineWidth || 0;
    var contentRect = this._contentRect = expandOrShrinkRect(boxRect.clone(), boxBorderWidth / 2, true, true);
    var contentGroup = new Group();
    group.add(contentGroup);
    contentGroup.setClipPath(new Rect({
      shape: contentRect.plain()
    }));
    var targetGroup = this._targetGroup = new Group();
    contentGroup.add(targetGroup);
    // Draw border and background and shadow of thumbnail box.
    var borderShape = boxRect.plain();
    borderShape.r = itemStyleModel.getShallow('borderRadius', true);
    group.add(this._bgRect = new Rect({
      style: itemStyle,
      shape: borderShape,
      silent: false,
      cursor: 'grab'
    }));
    var windowStyleModel = thumbnailModel.getModel('windowStyle');
    var windowR = windowStyleModel.getShallow('borderRadius', true);
    contentGroup.add(this._windowRect = new Rect({
      shape: {
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        r: windowR
      },
      style: windowStyleModel.getItemStyle(),
      silent: false,
      cursor: 'grab'
    }));
    this._dealRenderContent();
    this._dealUpdateWindow();
    updateZ(thumbnailModel, this);
  };
  /**
   * Can be called asynchronously directly.
   * This method should be idempotent.
   */
  ThumbnailView.prototype.renderContent = function (bridgeRendered) {
    this._bridgeRendered = bridgeRendered;
    if (this._isEnabled()) {
      this._dealRenderContent();
      this._dealUpdateWindow();
      updateZ(this._model, this);
    }
  };
  ThumbnailView.prototype._dealRenderContent = function () {
    var bridgeRendered = this._bridgeRendered;
    if (!bridgeRendered || bridgeRendered.renderVersion !== this._renderVersion) {
      return;
    }
    var targetGroup = this._targetGroup;
    var coordSys = this._coordSys;
    var contentRect = this._contentRect;
    targetGroup.removeAll();
    if (!bridgeRendered) {
      return;
    }
    var bridgeGroup = bridgeRendered.group;
    var bridgeRect = bridgeGroup.getBoundingRect();
    targetGroup.add(bridgeGroup);
    this._bgRect.z2 = bridgeRendered.z2Range.min - 10;
    viewCoordSysSetBoundingRect(coordSys, bridgeRect.x, bridgeRect.y, bridgeRect.width, bridgeRect.height);
    // Use `getLayoutRect` is just to find an appropriate rect in thumbnail.
    var viewRect = getLayoutRect({
      left: 'center',
      top: 'center',
      aspect: bridgeRect.width / bridgeRect.height
    }, contentRect);
    viewCoordSysSetViewRect(coordSys, viewRect.x, viewRect.y, viewRect.width, viewRect.height);
    viewCoordSysCopyTrans(bridgeGroup, coordSys, VIEW_COORD_SYS_TRANS_RAW);
    bridgeGroup.dirty();
    this._windowRect.z2 = bridgeRendered.z2Range.max + 10;
    this._resetRoamController(bridgeRendered.roamType);
  };
  /**
   * Can be called from action handler directly.
   * This method should be idempotent.
   */
  ThumbnailView.prototype.updateWindow = function (param) {
    var bridgeRendered = this._bridgeRendered;
    if (bridgeRendered && bridgeRendered.renderVersion === param.renderVersion) {
      bridgeRendered.targetTrans = param.targetTrans;
    }
    if (this._isEnabled()) {
      this._dealUpdateWindow();
    }
  };
  ThumbnailView.prototype._dealUpdateWindow = function () {
    var bridgeRendered = this._bridgeRendered;
    if (!bridgeRendered || bridgeRendered.renderVersion !== this._renderVersion) {
      return;
    }
    var invTargetTrans = matrix.invert([], bridgeRendered.targetTrans);
    var transTargetToThis = matrix.mul([], viewCoordSysCopyOverallMatrix(null, this._coordSys), invTargetTrans);
    this._transThisToTarget = matrix.invert([], transTargetToThis);
    var viewportRect = bridgeRendered.viewportRect;
    if (!viewportRect) {
      viewportRect = new BoundingRect(0, 0, this._api.getWidth(), this._api.getHeight());
    } else {
      viewportRect = viewportRect.clone();
    }
    viewportRect.applyTransform(transTargetToThis);
    var windowRect = this._windowRect;
    var r = windowRect.shape.r;
    windowRect.setShape(defaults({
      r: r
    }, viewportRect));
  };
  ThumbnailView.prototype._resetRoamController = function (roamType) {
    var _this = this;
    var api = this._api;
    var roamController = this._roamController;
    if (!roamController) {
      roamController = this._roamController = new RoamController(api.getZr());
    }
    if (!roamType || !this._isEnabled()) {
      roamController.disable();
      return;
    }
    roamController.enable(roamType, {
      api: api,
      zInfo: {
        component: this._model
      },
      triggerInfo: {
        roamTrigger: null,
        isInSelf: function (e, x, y) {
          return _this._contentRect.contain(x, y);
        }
      }
    });
    roamController.off('pan').off('zoom').on('pan', bind(this._onPan, this)).on('zoom', bind(this._onZoom, this));
    // PENDING: Currently roaming animation (when roaming args are changed;
    // e.g., `center` and `zoom` are changed) is not supported in thumbnail.
    // Animation should be able to be interrupted on pan and zoom, and synchronize
    // back to the target. See VIEW_COORD_SYS_ANIMATION.
  };
  ThumbnailView.prototype._onPan = function (event) {
    var trans = this._transThisToTarget;
    if (!this._isEnabled() || !trans) {
      return;
    }
    var oldOffset = applyTransform([], [event.oldX, event.oldY], trans);
    var newOffset = applyTransform([], [event.oldX - event.dx, event.oldY - event.dy], trans);
    this._api.dispatchAction(makeRoamPayload(this._model.getTarget().baseMapProvider, {
      dx: newOffset[0] - oldOffset[0],
      dy: newOffset[1] - oldOffset[1]
    }));
  };
  ThumbnailView.prototype._onZoom = function (event) {
    var trans = this._transThisToTarget;
    if (!this._isEnabled() || !trans) {
      return;
    }
    var offset = applyTransform([], [event.originX, event.originY], trans);
    this._api.dispatchAction(makeRoamPayload(this._model.getTarget().baseMapProvider, {
      zoom: 1 / event.scale,
      originX: offset[0],
      originY: offset[1]
    }));
  };
  /**
   * This method is also responsible for check enable in asynchronous situation,
   * e.g., in event listeners that is supposed to be outdated but not be removed.
   */
  ThumbnailView.prototype._isEnabled = function () {
    var thumbnailModel = this._model;
    if (!thumbnailModel || !thumbnailModel.shouldShow()) {
      return false;
    }
    var baseMapProvider = thumbnailModel.getTarget().baseMapProvider;
    if (!baseMapProvider) {
      return false;
    }
    return true;
  };
  ThumbnailView.prototype._clear = function () {
    this.group.removeAll();
    this._bridgeRendered = null;
    if (this._roamController) {
      this._roamController.disable();
    }
  };
  ThumbnailView.prototype.remove = function () {
    this._clear();
  };
  ThumbnailView.prototype.dispose = function () {
    this._clear();
  };
  ThumbnailView.type = 'thumbnail';
  return ThumbnailView;
}(ComponentView);
export { ThumbnailView };
function makeRoamPayload(baseMapProvider, params) {
  var type = baseMapProvider.mainType === 'series' ? baseMapProvider.subType + "Roam" // e.g. 'graphRoam'
  : baseMapProvider.mainType + "Roam"; // e.g., 'geoRoam'
  var payload = {
    type: type
  };
  payload[baseMapProvider.mainType + "Id"] = baseMapProvider.id;
  extend(payload, params);
  return payload;
}
function updateZ(thumbnailModel, thumbnailView) {
  var zInfo = retrieveZInfo(thumbnailModel);
  traverseUpdateZ(thumbnailView.group, zInfo.z, zInfo.zlevel);
}