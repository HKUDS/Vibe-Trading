
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
import Model from '../../model/Model.js';
import SeriesModel from '../../model/Series.js';
import createGraphFromNodeEdge from '../helper/createGraphFromNodeEdge.js';
import { createTooltipMarkup } from '../../component/tooltip/tooltipMarkup.js';
import LegendVisualProvider from '../../visual/LegendVisualProvider.js';
import * as zrUtil from 'zrender/lib/core/util.js';
export var SERIES_TYPE_CHORD = 'chord';
var ChordSeriesModel = /** @class */function (_super) {
  __extends(ChordSeriesModel, _super);
  function ChordSeriesModel() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = ChordSeriesModel.type;
    return _this;
  }
  ChordSeriesModel.prototype.init = function (option) {
    _super.prototype.init.apply(this, arguments);
    this.fillDataTextStyle(option.edges || option.links);
    // Enable legend selection for each data item
    this.legendVisualProvider = new LegendVisualProvider(zrUtil.bind(this.getData, this), zrUtil.bind(this.getRawData, this));
  };
  ChordSeriesModel.prototype.mergeOption = function (option) {
    _super.prototype.mergeOption.apply(this, arguments);
    this.fillDataTextStyle(option.edges || option.links);
  };
  ChordSeriesModel.prototype.getInitialData = function (option, ecModel) {
    var edges = option.edges || option.links || [];
    var nodes = option.data || option.nodes || [];
    if (nodes && edges) {
      var graph = createGraphFromNodeEdge(nodes, edges, this, true, beforeLink);
      return graph.data;
    }
    function beforeLink(nodeData, edgeData) {
      // TODO Inherit resolveParentPath by default in Model#getModel?
      var oldGetModel = Model.prototype.getModel;
      function newGetModel(path, parentModel) {
        var model = oldGetModel.call(this, path, parentModel);
        model.resolveParentPath = resolveParentPath;
        return model;
      }
      edgeData.wrapMethod('getItemModel', function (model) {
        model.resolveParentPath = resolveParentPath;
        model.getModel = newGetModel;
        return model;
      });
      function resolveParentPath(pathArr) {
        if (pathArr && (pathArr[0] === 'label' || pathArr[1] === 'label')) {
          var newPathArr = pathArr.slice();
          if (pathArr[0] === 'label') {
            newPathArr[0] = 'edgeLabel';
          } else if (pathArr[1] === 'label') {
            newPathArr[1] = 'edgeLabel';
          }
          return newPathArr;
        }
        return pathArr;
      }
    }
  };
  ChordSeriesModel.prototype.getGraph = function () {
    return this.getData().graph;
  };
  ChordSeriesModel.prototype.getEdgeData = function () {
    return this.getGraph().edgeData;
  };
  ChordSeriesModel.prototype.formatTooltip = function (dataIndex, multipleSeries, dataType) {
    var params = this.getDataParams(dataIndex, dataType);
    if (dataType === 'edge') {
      var nodeData = this.getData();
      var edge = nodeData.graph.getEdgeByIndex(dataIndex);
      var sourceName = nodeData.getName(edge.node1.dataIndex);
      var targetName = nodeData.getName(edge.node2.dataIndex);
      var nameArr = [];
      sourceName != null && nameArr.push(sourceName);
      targetName != null && nameArr.push(targetName);
      return createTooltipMarkup('nameValue', {
        name: nameArr.join(' > '),
        value: params.value,
        noValue: params.value == null
      });
    }
    // dataType === 'node' or empty
    return createTooltipMarkup('nameValue', {
      name: params.name,
      value: params.value,
      noValue: params.value == null
    });
  };
  ChordSeriesModel.prototype.getDataParams = function (dataIndex, dataType) {
    var params = _super.prototype.getDataParams.call(this, dataIndex, dataType);
    if (dataType === 'node') {
      var nodeData = this.getData();
      var node = this.getGraph().getNodeByIndex(dataIndex);
      // Set name if not already set
      if (params.name == null) {
        params.name = nodeData.getName(dataIndex);
      }
      // Set value if not already set
      if (params.value == null) {
        var nodeValue = node.getLayout().value;
        params.value = nodeValue;
      }
    }
    return params;
  };
  ChordSeriesModel.type = 'series.' + SERIES_TYPE_CHORD;
  ChordSeriesModel.defaultOption = {
    // zlevel: 0,
    z: 2,
    coordinateSystem: 'none',
    legendHoverLink: true,
    colorBy: 'data',
    left: 0,
    top: 0,
    right: 0,
    bottom: 0,
    width: null,
    height: null,
    center: ['50%', '50%'],
    radius: ['70%', '80%'],
    clockwise: true,
    startAngle: 90,
    endAngle: 'auto',
    minAngle: 0,
    padAngle: 3,
    itemStyle: {
      borderRadius: [0, 0, 5, 5]
    },
    lineStyle: {
      width: 0,
      color: 'source',
      opacity: 0.2
    },
    label: {
      show: true,
      position: 'outside',
      distance: 5
    },
    emphasis: {
      focus: 'adjacency',
      lineStyle: {
        opacity: 0.5
      }
    }
  };
  return ChordSeriesModel;
}(SeriesModel);
export default ChordSeriesModel;