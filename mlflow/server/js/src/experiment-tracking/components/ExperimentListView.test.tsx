import { beforeEach, jest, test, expect } from '@jest/globals';
import userEvent from '@testing-library/user-event';
import { screen, renderWithIntl, waitFor } from '../../common/utils/TestUtils.react18';
import { BrowserRouter } from '../../common/utils/RoutingUtils';
import { Provider } from 'react-redux';
import thunk from 'redux-thunk';
import configureStore from 'redux-mock-store';
import promiseMiddleware from 'redux-promise-middleware';
import { ExperimentListView } from './ExperimentListView';
import Fixtures from '../utils/test-utils/Fixtures';
import { DesignSystemProvider } from '@databricks/design-system';
import { useExperimentListQuery } from './experiment-page/hooks/useExperimentListQuery';
import { useUpdateExperimentTags } from './experiment-page/hooks/useUpdateExperimentTags';
import { useTagsFilter } from './experiment-page/hooks/useTagsFilter';
import { WorkflowType, WorkflowTypeContext } from '../../common/contexts/WorkflowTypeContext';
import { MlflowService } from '../sdk/MlflowService';

jest.mock('./experiment-page/hooks/useExperimentListQuery', () => ({
  useExperimentListQuery: jest.fn(),
  useInvalidateExperimentList: jest.fn(),
}));

jest.mock('./experiment-page/hooks/useUpdateExperimentTags', () => ({
  useUpdateExperimentTags: jest.fn(),
}));

jest.mock('./experiment-page/hooks/useTagsFilter', () => ({
  useTagsFilter: jest.fn(),
}));

let mockIsIntegrated = false;
jest.mock('../../common/utils/embedUtils', () => ({
  ...jest.requireActual<typeof import('../../common/utils/embedUtils')>('../../common/utils/embedUtils'),
  useIsIntegrated: () => mockIsIntegrated,
}));

beforeEach(() => {
  // The search filter lives in the URL, which jsdom keeps between tests
  // eslint-disable-next-line no-restricted-properties
  window.history.replaceState({}, '', '/');
});

const mountComponent = (props: {
  experiments: any[];
  tagsFilter?: any[];
  filterBySearch?: boolean;
  workflowType?: WorkflowType;
  isLocked?: boolean;
  integrated?: boolean;
}) => {
  mockIsIntegrated = props.integrated ?? false;
  const mockStore = configureStore([thunk, promiseMiddleware()]);

  jest.mocked(useExperimentListQuery).mockImplementation((params) => ({
    data: props.filterBySearch
      ? props.experiments.filter(({ name }) => name.includes(params?.searchFilter ?? ''))
      : props.experiments.slice(25),
    error: undefined,
    isLoading: false,
    hasNextPage: false,
    hasPreviousPage: false,
    onNextPage: jest.fn(),
    onPreviousPage: jest.fn(),
    // @ts-expect-error Type 'Mock<UnknownFunction>' is not assignable to parameter
    refetch: jest.fn(),
    pageSizeSelect: {
      options: [10],
      default: 10,
      onChange: jest.fn(),
    },
    sorting: [],
    setSorting: jest.fn(),
  }));

  jest.mocked(useUpdateExperimentTags).mockReturnValue({
    isLoading: false,
    EditTagsModal: <span />,
    showEditExperimentTagsModal: jest.fn(),
  });

  jest.mocked(useTagsFilter).mockReturnValue({
    tagsFilter: props.tagsFilter ?? [],
    setTagsFilter: jest.fn(),
    isTagsFilterOpen: false,
    setIsTagsFilterOpen: jest.fn(),
  });

  return renderWithIntl(
    <DesignSystemProvider>
      <Provider
        store={mockStore({
          entities: {
            experimentsById: {},
          },
        })}
      >
        <BrowserRouter>
          {props.workflowType ? (
            <WorkflowTypeContext.Provider
              value={{ workflowType: props.workflowType, setWorkflowType: jest.fn(), isLocked: props.isLocked }}
            >
              <ExperimentListView />
            </WorkflowTypeContext.Provider>
          ) : (
            <ExperimentListView />
          )}
        </BrowserRouter>
      </Provider>
    </DesignSystemProvider>,
  );
};

test('If button to create experiment is pressed then open CreateExperimentModal', async () => {
  mountComponent({ experiments: Fixtures.experiments });
  await userEvent.click(screen.getByTestId('create-experiment-table-empty-state-button'));
  expect(screen.getByRole('heading', { name: 'Create experiment' })).toBeInTheDocument();
});

test('should render when experiments are empty', () => {
  mountComponent({
    experiments: [],
  });

  // Get the sidebar header as proof that the component rendered
  expect(screen.getByText('Create your first experiment')).toBeInTheDocument();
});

test('paginated list should not render everything when there are many experiments', () => {
  const keys = Array.from(Array(1000).keys()).map((k) => k.toString());
  const localExperiments = keys.map((k) => Fixtures.createExperiment({ experimentId: k, name: k }));

  mountComponent({
    experiments: localExperiments,
  });
  const selected = screen.getAllByTestId('experiment-list-item');
  expect(selected.length).toBeLessThan(keys.length);
});

test('should show "No experiments found" when tags filter is active and experiments list is empty', () => {
  mountComponent({
    experiments: [],
    tagsFilter: [{ key: 'team', operator: 'IS', value: 'ml' }],
  });

  expect(screen.getByText('No experiments found')).toBeInTheDocument();
  expect(screen.queryByText('Create your first experiment')).not.toBeInTheDocument();
});

test('Tag filter button shows active filter count when filters are applied', () => {
  mountComponent({
    experiments: [],
    tagsFilter: [
      { key: 'team', operator: 'IS', value: 'alpha' },
      { key: 'project', operator: 'IS', value: 'nlp' },
    ],
  });

  expect(screen.getByRole('button', { name: /Tag · 2/ })).toBeInTheDocument();
});

test('Tag filter button shows no count when no filters are applied', () => {
  mountComponent({
    experiments: [],
    tagsFilter: [],
  });

  const tagButton = screen.getByRole('button', { name: /^Tag$/ });
  expect(tagButton).toBeInTheDocument();
  expect(tagButton).not.toHaveTextContent('·');
});

test('Delete button is disabled when checked experiments are hidden by the search filter', async () => {
  mountComponent({
    experiments: [
      Fixtures.createExperiment({ experimentId: '1', name: 'alpha-exp' }),
      Fixtures.createExperiment({ experimentId: '2', name: 'beta-exp' }),
    ],
    filterBySearch: true,
  });

  await userEvent.type(screen.getByTestId('search-experiment-input'), 'alpha{Enter}');
  await userEvent.click(screen.getByTestId('experiment-list-item-check-box'));
  expect(screen.getByTestId('delete-experiments-button')).toBeEnabled();

  await userEvent.clear(screen.getByTestId('search-experiment-input'));
  await userEvent.type(screen.getByTestId('search-experiment-input'), 'beta{Enter}');
  expect(await screen.findByText('beta-exp')).toBeInTheDocument();
  expect(screen.queryByText('alpha-exp')).not.toBeInTheDocument();
  expect(screen.getByTestId('delete-experiments-button')).toBeDisabled();
});

test.each([
  [WorkflowType.GENAI, true, true],
  [WorkflowType.GENAI, false, false],
  [WorkflowType.MACHINE_LEARNING, true, false],
  [WorkflowType.MACHINE_LEARNING, false, false],
])('when the workflow type is %s and locked is %s, genAIOnly is %s', (workflowType, isLocked, genAIOnly) => {
  mountComponent({ experiments: [], workflowType, isLocked });

  expect(useExperimentListQuery).toHaveBeenLastCalledWith(expect.objectContaining({ genAIOnly }));
});

test.each([
  [WorkflowType.GENAI, true, [{ key: 'mlflow.experimentKind', value: 'genai_development' }]],
  [WorkflowType.GENAI, false, [{ key: 'mlflow.experimentKind', value: 'genai_development' }]],
  [WorkflowType.MACHINE_LEARNING, true, undefined],
  [WorkflowType.MACHINE_LEARNING, false, undefined],
])(
  'when the workflow type is %s and locked is %s, new experiments get the tags %j',
  async (workflowType, isLocked, expectedTags) => {
    const createExperiment = jest.spyOn(MlflowService, 'createExperiment').mockResolvedValue({ experiment_id: '1' });
    mountComponent({ experiments: [], workflowType, isLocked });

    await userEvent.click(screen.getByTestId('create-experiment-table-empty-state-button'));
    await userEvent.type(screen.getByPlaceholderText('Input an experiment name'), 'my-agent');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(createExperiment).toHaveBeenCalledWith(expect.objectContaining({ name: 'my-agent' })));
    expect(createExperiment.mock.calls[0][0].tags).toEqual(expectedTags);
    createExperiment.mockRestore();
  },
);

test.each([
  [WorkflowType.GENAI, true, 'rh-no-agent-traces.svg'],
  [WorkflowType.GENAI, false, 'rh-no-experiments.svg'],
  [WorkflowType.MACHINE_LEARNING, true, 'rh-no-experiments.svg'],
  [WorkflowType.MACHINE_LEARNING, false, 'rh-no-experiments.svg'],
])(
  'when embedded with workflow type %s and locked is %s, the empty state illustration is %s',
  (workflowType, isLocked, illustration) => {
    mountComponent({ experiments: [], workflowType, isLocked, integrated: true });

    expect(screen.getByText('No experiments')).toBeInTheDocument();
    expect(screen.getByTestId('experiments-empty-state-illustration')).toHaveAttribute(
      'src',
      expect.stringContaining(illustration),
    );
  },
);
