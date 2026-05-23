
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
import SymbolDraw from '../helper/SymbolDraw.js';
import LineDraw from '../helper/LineDraw.js';
import RoamController from '../../component/helper/RoamController.js';
import { isRoamPayloadHasZoom, updateRoamControllerSimply } from '../../component/helper/roamHelper.js';
import * as graphic from '../../util/graphic.js';
import adjustEdge from './adjustEdge.js';
import { getNodeGlobalScale } from './graphHelper.js';
import ChartView from '../../view/Chart.js';
import { SERIES_TYPE_GRAPH } from './GraphSeries.js';
import { applyViewCoordSysTransToElement, getOwnRoamViewCoordSys, VIEW_COORD_SYS_TRANS_OVERALL, viewCoordSysCopyOverallMatrix } from '../../coord/View.js';
import { getECData } from '../../util/innerStore.js';
import { simpleLayoutEdge } from './simpleLayoutHelper.js';
import { circularLayout, rotateNodeLabel } from './circularLayoutHelper.js';
import { clone, extend } from 'zrender/lib/core/util.js';
import ECLinePath from '../helper/LinePath.js';
import { getThumbnailBridge } from '../../component/helper/thumbnailBridge.js';
var GraphView = /** @class */function (_super) {
  __extends(GraphView, _super);
  function GraphView() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = SERIES_TYPE_GRAPH;
    return _this;
  }
  GraphView.prototype.init = function (ecModel, api) {
    var symbolDraw = new SymbolDraw();
    var lineDraw = new LineDraw();
    var group = this.group;
    var mainGroup = new graphic.Group();
    this._controller = new RoamController(api.getZr());
    mainGroup.add(symbolDraw.group);
    mainGroup.add(lineDraw.group);
    group.add(mainGroup);
    this._symbolDraw = symbolDraw;
    this._lineDraw = lineDraw;
    this._mainGroup = mainGroup;
    this._firstRender = true;
  };
  GraphView.prototype.render = function (seriesModel, ecModel, api) {
    var _this = this;
    var ownCoordSys = getOwnRoamViewCoordSys(seriesModel);
    var isForceLayout = false;
    this._model = seriesModel;
    this._api = api;
    this._active = true;
    var mainGroup = this._mainGroup;
    var thumbnailInfo = this._getThumbnailInfo();
    if (thumbnailInfo) {
      thumbnailInfo.bridge.reset(api);
    }
    var symbolDraw = this._symbolDraw;
    var lineDraw = this._lineDraw;
    if (ownCoordSys) {
      applyViewCoordSysTransToElement(mainGroup, VIEW_COORD_SYS_TRANS_OVERALL, ownCoordSys, this._firstRender ? null : seriesModel);
    }
    // Fix edge contact point with node
    adjustEdge(seriesModel.getGraph(), getNodeGlobalScale(seriesModel));
    var data = seriesModel.getData();
    symbolDraw.updateData(data);
    var edgeData = seriesModel.getEdgeData();
    // TODO: TYPE
    lineDraw.updateData(edgeData);
    this._updateNodeAndLinkScale();
    if (ownCoordSys) {
      updateRoamControllerSimply(seriesModel, api, this._controller, function (e, x, y) {
        return seriesModel.coordinateSystem.containPoint([x, y]);
      }, null);
    }
    clearTimeout(this._layoutTimeout);
    var forceLayout = seriesModel.forceLayout;
    var layoutAnimation = seriesModel.get(['force', 'layoutAnimation']);
    if (forceLayout) {
      isForceLayout = true;
      this._startForceLayoutIteration(forceLayout, api, layoutAnimation);
    }
    var layout = seriesModel.get('layout');
    data.graph.eachNode(function (node) {
      var idx = node.dataIndex;
      var el = node.getGraphicEl();
      var itemModel = node.getModel();
      if (!el) {
        return;
      }
      // Update draggable
      el.off('drag').off('dragend');
      var draggable = itemModel.get('draggable');
      if (draggable) {
        el.on('drag', function (e) {
          switch (layout) {
            case 'force':
              forceLayout.warmUp();
              !_this._layouting && _this._startForceLayoutIteration(forceLayout, api, layoutAnimation);
              forceLayout.setFixed(idx);
              // Write position back to layout
              data.setItemLayout(idx, [el.x, el.y]);
              break;
            case 'circular':
              data.setItemLayout(idx, [el.x, el.y]);
              // mark node fixed
              node.setLayout({
                fixed: true
              }, true);
              // recalculate circular layout
              circularLayout(seriesModel, 'symbolSize', node, [e.offsetX, e.offsetY]);
              _this.updateLayout(seriesModel);
              break;
            case 'none':
            default:
              data.setItemLayout(idx, [el.x, el.y]);
              // update edge
              simpleLayoutEdge(seriesModel.getGraph(), seriesModel);
              _this.updateLayout(seriesModel);
              break;
          }
        }).on('dragend', function () {
          if (forceLayout) {
            forceLayout.setUnfixed(idx);
          }
        });
      }
      el.setDraggable(draggable, !!itemModel.get('cursor'));
      var focus = itemModel.get(['emphasis', 'focus']);
      if (focus === 'adjacency') {
        getECData(el).focus = node.getAdjacentDataIndices();
      }
    });
    data.graph.eachEdge(function (edge) {
      var el = edge.getGraphicEl();
      var focus = edge.getModel().get(['emphasis', 'focus']);
      if (!el) {
        return;
      }
      if (focus === 'adjacency') {
        getECData(el).focus = {
          edge: [edge.dataIndex],
          node: [edge.node1.dataIndex, edge.node2.dataIndex]
        };
      }
    });
    var circularRotateLabel = seriesModel.get('layout') === 'circular' && seriesModel.get(['circular', 'rotateLabel']);
    var cx = data.getLayout('cx');
    var cy = data.getLayout('cy');
    data.graph.eachNode(function (node) {
      rotateNodeLabel(node, circularRotateLabel, cx, cy);
    });
    this._firstRender = false;
    // Force layout will render thumbnail when layout is finished.
    if (!isForceLayout) {
      this._renderThumbnail(seriesModel, api, this._symbolDraw, this._lineDraw);
    }
  };
  GraphView.prototype.dispose = function () {
    this.remove();
    this._controller && this._controller.dispose();
  };
  GraphView.prototype._startForceLayoutIteration = function (forceLayout, api, layoutAnimation) {
    var self = this;
    var firstRendered = false;
    (function step() {
      forceLayout.step(function (stopped) {
        self.updateLayout(self._model);
        if (stopped || !firstRendered) {
          firstRendered = true;
          self._renderThumbnail(self._model, api, self._symbolDraw, self._lineDraw);
        }
        (self._layouting = !stopped) && (layoutAnimation ? self._layoutTimeout = setTimeout(step, 16) : step());
      });
    })();
  };
  /**
   * @implements RoamHostView['__updateOnOwnRoam']
   */
  GraphView.prototype.__updateOnOwnRoam = function (payload, seriesModel, api) {
    var ownCoordSys = getOwnRoamViewCoordSys(seriesModel);
    if (!this._active || !ownCoordSys) {
      return;
    }
    applyViewCoordSysTransToElement(this._mainGroup, VIEW_COORD_SYS_TRANS_OVERALL, ownCoordSys, null);
    if (isRoamPayloadHasZoom(payload)) {
      this._updateNodeAndLinkScale();
      adjustEdge(seriesModel.getGraph(), getNodeGlobalScale(seriesModel));
      this._lineDraw.updateLayout();
      // Only update label layout on zoom
      api.updateLabelLayout();
    }
    this._updateThumbnailWindow();
  };
  GraphView.prototype._updateNodeAndLinkScale = function () {
    var seriesModel = this._model;
    var data = seriesModel.getData();
    var nodeScale = getNodeGlobalScale(seriesModel);
    data.eachItemGraphicEl(function (el, idx) {
      el && el.setSymbolScale(nodeScale);
    });
  };
  GraphView.prototype.updateLayout = function (seriesModel) {
    if (!this._active) {
      return;
    }
    adjustEdge(seriesModel.getGraph(), getNodeGlobalScale(seriesModel));
    this._symbolDraw.updateLayout();
    this._lineDraw.updateLayout();
  };
  GraphView.prototype.remove = function () {
    this._active = false;
    clearTimeout(this._layoutTimeout);
    this._layouting = false;
    this._layoutTimeout = null;
    this._symbolDraw && this._symbolDraw.remove();
    this._lineDraw && this._lineDraw.remove();
    this._controller && this._controller.disable();
  };
  /**
   * Get thumbnail data structure only if supported.
   */
  GraphView.prototype._getThumbnailInfo = function () {
    var model = this._model;
    var coordSys = model.coordinateSystem;
    if (coordSys.type !== 'view') {
      return;
    }
    var bridge = getThumbnailBridge(model);
    if (!bridge) {
      return;
    }
    return {
      bridge: bridge,
      coordSys: coordSys
    };
  };
  GraphView.prototype._updateThumbnailWindow = function () {
    var info = this._getThumbnailInfo();
    if (info) {
      info.bridge.updateWindow(viewCoordSysCopyOverallMatrix(null, info.coordSys), this._api);
    }
  };
  GraphView.prototype._renderThumbnail = function (seriesModel, api, symbolDraw, lineDraw) {
    var info = this._getThumbnailInfo();
    if (!info) {
      return;
    }
    var bridgeGroup = new graphic.Group();
    var symbolNodes = symbolDraw.group.children();
    var lineNodes = lineDraw.group.children();
    var lineGroup = new graphic.Group();
    var symbolGroup = new graphic.Group();
    bridgeGroup.add(symbolGroup);
    bridgeGroup.add(lineGroup);
    // TODO: reuse elements for performance in large graph?
    for (var i = 0; i < symbolNodes.length; i++) {
      var node = symbolNodes[i];
      var sub = node.children()[0];
      var x = node.x;
      var y = node.y;
      var subShape = clone(sub.shape);
      var shape = extend(subShape, {
        width: sub.scaleX,
        height: sub.scaleY,
        x: x - sub.scaleX / 2,
        y: y - sub.scaleY / 2
      });
      var style = clone(sub.style);
      var subThumbnail = new sub.constructor({
        shape: shape,
        style: style,
        z2: 151
      });
      symbolGroup.add(subThumbnail);
    }
    for (var i = 0; i < lineNodes.length; i++) {
      var node = lineNodes[i];
      var line = node.children()[0];
      var style = clone(line.style);
      var shape = clone(line.shape);
      var lineThumbnail = new ECLinePath({
        style: style,
        shape: shape,
        z2: 151
      });
      lineGroup.add(lineThumbnail);
    }
    info.bridge.renderContent({
      api: api,
      roamType: seriesModel.get('roam'),
      viewportRect: null,
      group: bridgeGroup,
      targetTrans: viewCoordSysCopyOverallMatrix(null, info.coordSys)
    });
  };
  GraphView.type = SERIES_TYPE_GRAPH;
  return GraphView;
}(ChartView);
export default GraphView;