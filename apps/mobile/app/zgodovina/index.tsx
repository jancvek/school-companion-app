import { useRouter } from 'expo-router';

import { SubjectList } from '@/ui/subject-list';

export default function PickSubjectForHistoryScreen() {
  const router = useRouter();

  return (
    <SubjectList
      onSelect={(subject) =>
        router.push({
          pathname: '/zgodovina/[subject]',
          params: { subject: subject.value },
        })
      }
    />
  );
}
