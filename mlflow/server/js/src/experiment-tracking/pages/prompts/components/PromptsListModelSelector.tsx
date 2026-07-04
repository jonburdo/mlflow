import {
  DialogCombobox,
  DialogComboboxContent,
  DialogComboboxOptionList,
  DialogComboboxOptionListSearch,
  DialogComboboxOptionListSelectItem,
  DialogComboboxTrigger,
} from '@databricks/design-system';
import { useMemo } from 'react';
import { useIntl } from 'react-intl';
import type { RegisteredPrompt } from '../types';
import { getPromptAssociatedModel } from '../promptModelConfig';

export const PromptsListModelSelector = ({
  modelFilter,
  setModelFilter,
  prompts,
}: {
  modelFilter?: string;
  setModelFilter: (modelFilter?: string) => void;
  prompts: RegisteredPrompt[];
}) => {
  const intl = useIntl();
  const models = useMemo(
    () =>
      Array.from(
        new Set(prompts.map(getPromptAssociatedModel).filter((model): model is string => model !== undefined)),
      ).sort(),
    [prompts],
  );

  return (
    <DialogCombobox
      componentId="mlflow.prompts.list.model-selector"
      label={intl.formatMessage({
        defaultMessage: 'Associated model',
        description: 'Label for the associated model filter on the registered prompts page',
      })}
      modal={false}
      value={modelFilter ? [modelFilter] : undefined}
    >
      <DialogComboboxTrigger
        allowClear
        placeholder={intl.formatMessage({
          defaultMessage: 'All models',
          description: 'Placeholder for the associated model filter when no model is selected',
        })}
        onClear={() => setModelFilter(undefined)}
      />
      <DialogComboboxContent maxHeight={400} matchTriggerWidth>
        <DialogComboboxOptionList>
          <DialogComboboxOptionListSearch autoFocus>
            {models.map((model) => (
              <DialogComboboxOptionListSelectItem
                key={model}
                value={model}
                checked={modelFilter === model}
                onChange={(value) => setModelFilter(modelFilter === value ? undefined : value)}
              >
                {model}
              </DialogComboboxOptionListSelectItem>
            ))}
          </DialogComboboxOptionListSearch>
        </DialogComboboxOptionList>
      </DialogComboboxContent>
    </DialogCombobox>
  );
};
