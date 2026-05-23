
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
import { extend, retrieve3 } from 'zrender/lib/core/util.js';
import * as graphic from '../../util/graphic.js';
import { getSectorCornerRadius } from '../helper/sectorHelper.js';
import { getLabelStatesModels, setLabelStyle } from '../../label/labelStyle.js';
import { setStatesStylesFromModel, toggleHoverEmphasis } from '../../util/states.js';
import { getECData } from '../../util/innerStore.js';
var ChordPiece = /** @class */function (_super) {
  __extends(ChordPiece, _super);
  function ChordPiece(data, idx, startAngle) {
    var _this = _super.call(this) || this;
    getECData(_this).dataType = 'node';
    _this.z2 = 2;
    var text = new graphic.Text();
    _this.setTextContent(text);
    _this.updateData(data, idx, startAngle, true);
    return _this;
  }
  ChordPiece.prototype.updateData = function (data, idx, startAngle, firstCreate) {
    var sector = this;
    var node = data.graph.getNodeByIndex(idx);
    var seriesModel = data.hostModel;
    var itemModel = node.getModel();
    var emphasisModel = itemModel.getModel('emphasis');
    // layout position is the center of the sector
    var layout = data.getItemLayout(idx);
    var shape = extend(getSectorCornerRadius(itemModel.getModel('itemStyle'), layout, true), layout);
    var el = this;
    // Ignore NaN data.
    if (isNaN(shape.startAngle)) {
      // Use NaN shape to avoid drawing shape.
      el.setShape(shape);
      return;
    }
    if (firstCreate) {
      el.setShape(shape);
    } else {
      graphic.updateProps(el, {
        shape: shape
      }, seriesModel, idx);
    }
    var sectorShape = extend(getSectorCornerRadius(itemModel.getModel('itemStyle'), layout, true), layout);
    sector.setShape(sectorShape);
    sector.useStyle(data.getItemVisual(idx, 'style'));
    setStatesStylesFromModel(sector, itemModel);
    this._updateLabel(seriesModel, itemModel, node);
    data.setItemGraphicEl(idx, el);
    setStatesStylesFromModel(el, itemModel, 'itemStyle');
    // Add focus/blur states handling
    var focus = emphasisModel.get('focus');
    toggleHoverEmphasis(this, focus === 'adjacency' ? node.getAdjacentDataIndices() : focus, emphasisModel.get('blurScope'), emphasisModel.get('disabled'));
  };
  ChordPiece.prototype._updateLabel = function (seriesModel, itemModel, node) {
    var label = this.getTextContent();
    var layout = node.getLayout();
    var midAngle = (layout.startAngle + layout.endAngle) / 2;
    var dx = Math.cos(midAngle);
    var dy = Math.sin(midAngle);
    var normalLabelModel = itemModel.getModel('label');
    label.ignore = !normalLabelModel.get('show');
    // Set label style
    var labelStateModels = getLabelStatesModels(itemModel);
    var style = node.getVisual('style');
    setLabelStyle(label, labelStateModels, {
      labelFetcher: {
        getFormattedLabel: function (dataIndex, stateName, dataType, labelDimIndex, formatter, extendParams) {
          return seriesModel.getFormattedLabel(dataIndex, stateName, 'node', labelDimIndex,
          // ensure edgeLabel formatter is provided
          // to prevent the inheritance from `label.formatter` of the series
          retrieve3(formatter, labelStateModels.normal && labelStateModels.normal.get('formatter'), itemModel.get('name')), extendParams);
        }
      },
      labelDataIndex: node.dataIndex,
      defaultText: node.dataIndex + '',
      inheritColor: style.fill,
      defaultOpacity: style.opacity,
      defaultOutsidePosition: 'startArc'
    });
    // Set label position
    var labelPosition = normalLabelModel.get('position') || 'outside';
    var labelPadding = normalLabelModel.get('distance') || 0;
    var r;
    if (labelPosition === 'outside') {
      r = layout.r + labelPadding;
    } else {
      r = (layout.r + layout.r0) / 2;
    }
    this.textConfig = {
      inside: labelPosition !== 'outside'
    };
    var align = labelPosition !== 'outside' ? normalLabelModel.get('align') || 'center' : dx > 0 ? 'left' : 'right';
    var verticalAlign = labelPosition !== 'outside' ? normalLabelModel.get('verticalAlign') || 'middle' : dy > 0 ? 'top' : 'bottom';
    label.attr({
      x: dx * r + layout.cx,
      y: dy * r + layout.cy,
      rotation: 0,
      style: {
        align: align,
        verticalAlign: verticalAlign
      }
    });
  };
  return ChordPiece;
}(graphic.Sector);
export default ChordPiece;