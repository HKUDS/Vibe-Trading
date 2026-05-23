import MatrixModel from '../../coord/matrix/MatrixModel.js';
import ComponentView from '../../view/Component.js';
import GlobalModel from '../../model/Global.js';
declare class MatrixView extends ComponentView {
    static type: string;
    type: string;
    render(matrixModel: MatrixModel, ecModel: GlobalModel): void;
}
export default MatrixView;
